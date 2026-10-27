/* Included only by uvm_map_external.c, after its existing functions.
 * Diagnostic only:4 bytes, current CUDA VA-space, exact two native GPUs.
 * ABI2 adds isolated raw physical PULL; stock HAL peer-read policy is unchanged.
 * C7B5 describes SYS source physical methods, but UVM rejects peer-classified
 * sources. This experiment is not vendor-supported P2P, nor proof that only
 * virtual translation differs from CUDA copies.
 * Never accepts a user physical address or derives one from a log.
 */
#include "uvm_test.h"
#include "uvm_channel.h"
#include "uvm_push_macros.h"
#include "clc6b5.h"
#include "clc7b5.h"
#include "hwref/turing/tu102/dev_mmu.h"
#include <linux/capability.h>
#include <linux/module.h>
#include <linux/pci.h>
#include <asm/processor.h>
#include <asm/cpufeature.h>

static bool uvm_cask_physical_ce;
module_param(uvm_cask_physical_ce, bool, 0400);
MODULE_PARM_DESC(uvm_cask_physical_ce, "Native CaskLogic4-byte raw physical PUSH/PULL diagnostic ABI2; default off");
static DEFINE_MUTEX(cask_phys_serial);
static bool cask_phys_fatal;
/* On unconfirmed completion these references deliberately survive until reboot. */
static uvm_ext_gpu_mem_handle *cask_phys_held_maps[3];
static uvm_gpu_t *cask_phys_held_gpus[2];
/* This is an extra PCIe peer reference, which also retains both GPUs. */
static bool cask_phys_held_peer;

static bool cask_phys_gpu(uvm_gpu_t *gpu, int index)
{
    struct pci_dev *pci = gpu ? gpu->parent->pci_dev : NULL;
    return pci && pci_domain_nr(pci->bus)==0 && pci->vendor==0x10de &&
           pci->device==(index==0 ? 0x28b0 : 0x2571) &&
           pci->bus->number==(index==0 ? 1 : 6) && pci->devfn==0;
}

static int cask_phys_identity(const NvU8 *uuid)
{
    static const NvU8 ids[2][16] = {
        {0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x01},
        {0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x02}
    };
    if (!memcmp(uuid,ids[0],16)) return 0;
    if (!memcmp(uuid,ids[1],16)) return 1;
    return -1;
}

static const char *cask_phys_bdf(uvm_gpu_t *gpu)
{
    return gpu && gpu->parent && gpu->parent->pci_dev ? pci_name(gpu->parent->pci_dev) : "none";
}

static NV_STATUS cask_phys_map(uvm_va_space_t *space, uvm_gpu_t *requester,
                              uvm_gpu_t *owner, NvU64 va,
                              uvm_ext_gpu_map_t **out, NvU64 *offset,
                              NvU64 request, const char *role)
{
    uvm_va_range_external_t *range=uvm_va_range_external_find(space,va);
    uvm_ext_gpu_map_t *map;
    NvU64 delta;
    NvU32 guards=0;
    NV_STATUS status;
    pr_info("CASKPHYS request=%llu stage=map_lookup role=%s va=%llx requester=%s owner=%s range_present=%u\n",
            request,role,va,cask_phys_bdf(requester),cask_phys_bdf(owner),!!range);
    if (!range || va>NV_U64_MAX-3 || range->va_range.node.end<va+3)
        return NV_ERR_INVALID_ADDRESS;
    pr_info("CASKPHYS request=%llu stage=map_range role=%s range_start=%llx range_end=%llx\n",
            request,role,range->va_range.node.start,range->va_range.node.end);
    map=uvm_va_range_ext_gpu_map(range,requester,va);
    if (!map) {
        pr_info("CASKPHYS request=%llu stage=map_reject role=%s reason=map_absent\n",request,role);
        return NV_ERR_INVALID_STATE;
    }
    /* Each bit independently reports a satisfied guard. Never infer writable
     * permissions from Default: EXECUTE still queries RM with explicit RW and
     * RM rejects a DEVICE_READ_ONLY descriptor before any CE method is issued. */
    guards |= (!!map->mem_handle) << 0;
    guards |= (!!(map->mem_handle && map->mem_handle->rm_handle)) << 1;
    guards |= (map->gpu==requester) << 2;
    guards |= (!!(map->mem_handle && map->mem_handle->gpu==requester)) << 3;
    guards |= (map->owning_gpu==owner) << 4;
    guards |= (!map->is_sysmem) << 5;
    guards |= (!map->is_egm) << 6;
    guards |= (!!map->cask_phys_recorded) << 7;
    guards |= (!!map->cask_phys_device_descendant) << 8;
    /* TU102+ GENERIC_MEMORY (6) is noncompressible and not kind-swizzled.
     * Keep PITCH (0) from v2; reject all compression/surface-specific kinds.
     * This is a raw four-byte physical copy of a plain CUDA VMM allocation,
     * not a general block-linear-to-pitch conversion or compression operation. */
    guards |= ((map->cask_phys_kind==NV_MMU_PTE_KIND_PITCH ||
                map->cask_phys_kind==NV_MMU_PTE_KIND_GENERIC_MEMORY)) << 9;
    guards |= (map->cask_phys_format==UvmGpuFormatTypeDefault) << 10;
    guards |= (map->cask_phys_page_size>=4096 && !(map->cask_phys_page_size%4096)) << 11;
    guards |= (map->node.start==map->cask_phys_origin_start) << 12;
    guards |= (map->node.end==map->cask_phys_origin_end) << 13;
    guards |= (map->node.end>=va+3) << 14;
    guards |= ((map->cask_phys_mapping_type==UvmGpuMappingTypeDefault ||
                map->cask_phys_mapping_type==UvmGpuMappingTypeReadWrite ||
                map->cask_phys_mapping_type==UvmGpuMappingTypeReadWriteAtomic)) << 15;
    pr_info("CASKPHYS request=%llu stage=map_guards role=%s bits=%04x expected=ffff handle=%u rm_handle=%u map_gpu=%u handle_gpu=%u owner=%u vidmem=%u non_egm=%u recorded=%u descendant=%u kind=%u format=%u page=%u start=%u end=%u contains=%u permissions=%u\n",
            request,role,guards,(guards>>0)&1,(guards>>1)&1,(guards>>2)&1,(guards>>3)&1,
            (guards>>4)&1,(guards>>5)&1,(guards>>6)&1,(guards>>7)&1,(guards>>8)&1,
            (guards>>9)&1,(guards>>10)&1,(guards>>11)&1,(guards>>12)&1,(guards>>13)&1,
            (guards>>14)&1,(guards>>15)&1);
    pr_info("CASKPHYS request=%llu stage=map_meta role=%s recorded=%u device_descendant=%u kind=%x format=%u mapping_type=%u page_size=%llx sysmem=%u egm=%u rm_handle=%x\n",
            request,role,map->cask_phys_recorded,map->cask_phys_device_descendant,
            map->cask_phys_kind,map->cask_phys_format,map->cask_phys_mapping_type,
            map->cask_phys_page_size,map->is_sysmem,map->is_egm,
            map->mem_handle ? map->mem_handle->rm_handle : 0);
    pr_info("CASKPHYS request=%llu stage=map_identity role=%s map_gpu=%s handle_gpu=%s owning_gpu=%s user_client=%x user_object=%x\n",
            request,role,cask_phys_bdf(map->gpu),
            cask_phys_bdf(map->mem_handle ? map->mem_handle->gpu : NULL),
            cask_phys_bdf(map->owning_gpu),map->cask_phys_user_client,map->cask_phys_user_object);
    pr_info("CASKPHYS request=%llu stage=map_geometry role=%s node_start=%llx node_end=%llx origin_start=%llx origin_end=%llx map_offset=%llx allocation_size=%llx\n",
            request,role,map->node.start,map->node.end,map->cask_phys_origin_start,
            map->cask_phys_origin_end,map->cask_phys_map_offset,map->cask_phys_allocation_size);
    if (guards!=0xffff) return NV_ERR_INVALID_STATE;
    /* Reject split/rebound aliases. Metadata came from successful RM duplication. */
    delta=va-map->cask_phys_origin_start;
    if (delta>NV_U64_MAX-map->cask_phys_map_offset)
        return NV_ERR_INVALID_LIMIT;
    *offset=map->cask_phys_map_offset+delta;
    /* Scope is the first word of the unformatted allocation only. Do not
     * generalize kind6 into a surface-layout conversion for interior offsets. */
    if (*offset!=0 || va!=map->cask_phys_origin_start ||
        *offset>map->cask_phys_allocation_size ||
        map->cask_phys_allocation_size-*offset<4 ||
        (*offset&3) || (*offset&4095)>4092 ||
        map->cask_phys_allocation_size-(*offset&~4095ULL)<4096) {
        pr_info("CASKPHYS request=%llu stage=map_bounds_reject role=%s offset=%llx allocation_size=%llx\n",
                request,role,*offset,map->cask_phys_allocation_size);
        return NV_ERR_INVALID_LIMIT;
    }
    *out=map;
    status=uvm_tracker_wait(&map->tracker);
    pr_info("CASKPHYS request=%llu stage=map_ready role=%s offset=%llx tracker_status=%x\n",
            request,role,*offset,status);
    return status;
}

static NV_STATUS cask_phys_query(uvm_gpu_va_space_t *gpu_space,
                                uvm_ext_gpu_map_t *map, NvU64 offset, NvU64 *pa,
                                NvU64 request, const char *role)
{
    UvmGpuExternalPhysAddrInfo info={0};
    NvU64 base=0;
    NV_STATUS status;
    info.mappingType=UvmGpuMappingTypeReadWrite;
    info.mappingPageSize=4096;
    info.physAddrBuffer=&base;
    info.physAddrBufferSize=sizeof(base);
    /* One4KiB page only, so the RM count cannot exceed our one-entry buffer. */
    status=uvm_rm_locked_call(nvUvmInterfaceGetExternalAllocPhysAddrs(
        gpu_space->duped_gpu_va_space,map->mem_handle->rm_handle,
        offset&~4095ULL,4096,&info));
    pr_info("CASKPHYS request=%llu stage=query_result role=%s mapping_type=%u offset=%llx page=1000 bytes=1000 status=%x written=%llu remaining=%llu base=%llx\n",
            request,role,info.mappingType,offset&~4095ULL,status,
            info.numWrittenPhysAddrs,info.numRemainingPhysAddrs,base);
    if (status!=NV_OK) return status;
    if (info.numWrittenPhysAddrs!=1 || info.numRemainingPhysAddrs!=0 ||
        (base&4095) || base>NV_U64_MAX-(offset&4095))
        return NV_ERR_INVALID_STATE;
    *pa=base+(offset&4095);
    return NV_OK;
}

NV_STATUS uvm_test_cask_physical_ce(UVM_TEST_CASK_PHYSICAL_CE_PARAMS *p, struct file *filp)
{
    uvm_va_space_t *space=uvm_va_space_get(filp);
    NvProcessorUuid source_uuid,destination_uuid;
    uvm_gpu_t *src=NULL,*dst=NULL,*requester=NULL,*remote=NULL;
    uvm_gpu_va_space_t *requester_space;
    uvm_ext_gpu_map_t *src_map=NULL,*dst_map=NULL,*remote_map=NULL,*remote_owner_map=NULL;
    NvU64 src_offset=0,dst_offset=0,owner_offset=0,remote_offset,bar,bar_size,local_pa,remote_pa;
    uvm_aperture_t remote_aperture;
    uvm_push_t push_storage;
    uvm_push_t *push=&push_storage;
    NV_STATUS status=NV_ERR_INVALID_ARGUMENT;
    bool retained=false,inflight=false,peer_retained=false,pull;
    int source_index,destination_index,j;
    NvU32 plc;
    const char *stage="entry";
    BUILD_BUG_ON(sizeof(*p)!=176);
    BUILD_BUG_ON(UVM_TEST_CASK_PHYSICAL_CE!=CASK_PHYS_CE_IOCTL);
    BUILD_BUG_ON(offsetof(UVM_TEST_CASK_PHYSICAL_CE_PARAMS,source_va)!=64);
    BUILD_BUG_ON(offsetof(UVM_TEST_CASK_PHYSICAL_CE_PARAMS,source_physical)!=96);
    BUILD_BUG_ON(offsetof(UVM_TEST_CASK_PHYSICAL_CE_PARAMS,result_flags)!=152);
    /* Reset each output separately to respect FORTIFY field bounds. */
    p->source_physical=0;p->destination_physical=0;
    p->source_allocation_offset=0;p->destination_allocation_offset=0;
    p->source_rm_handle=0;p->destination_rm_handle=0;
    p->ce_class=0;p->launch_dma=0;
    p->source_phys_mode=0;p->destination_phys_mode=0;
    p->result_flags=0;p->rmStatus=0;p->reserved_out=0;
    p->source_is_peer=0;p->destination_is_peer=0;p->stock_rejects_peer_source=0;
    if (!uvm_cask_physical_ce || !capable(CAP_SYS_ADMIN)) return NV_ERR_INSUFFICIENT_PERMISSIONS;
    if (boot_cpu_data.x86_vendor!=X86_VENDOR_INTEL || boot_cpu_data.x86!=6 ||
        boot_cpu_data.x86_model!=0x9a || boot_cpu_data.x86_stepping!=3 || boot_cpu_has(X86_FEATURE_HYPERVISOR))
        return NV_ERR_NOT_SUPPORTED;
    if (p->abi_version!=CASK_PHYS_CE_ABI || p->operation>CASK_PHYS_CE_EXECUTE ||
        p->transfer>CASK_PHYS_CE_PULL ||
        (p->remote_phys_mode!=CASK_PHYS_CE_REMOTE_COHERENT &&
         p->remote_phys_mode!=CASK_PHYS_CE_REMOTE_NONCOHERENT) ||
        !p->request_id || p->bytes!=4 || p->reserved || (p->source_va&3) ||
        (p->destination_va&3) || p->source_va==p->destination_va)
        return NV_ERR_INVALID_ARGUMENT;
    pull=p->transfer==CASK_PHYS_CE_PULL;
    if (memcmp(p->executor_uuid,pull?p->destination_uuid:p->source_uuid,16))
        return NV_ERR_INVALID_DEVICE;
    source_index=cask_phys_identity(p->source_uuid);
    destination_index=cask_phys_identity(p->destination_uuid);
    if (source_index<0 || destination_index<0 || source_index==destination_index)
        return NV_ERR_INVALID_DEVICE;
    memcpy(&source_uuid,p->source_uuid,16);memcpy(&destination_uuid,p->destination_uuid,16);
    mutex_lock(&cask_phys_serial);
    stage="serial";
    if (cask_phys_fatal) {status=NV_ERR_INVALID_STATE;goto unlock_serial;}
    /* Retain existing pair under global lock before acquiring the VA lock.
     * No peer creation, changes to global HAL, or arbitrary physical inputs. */
    stage="peer_retain";
    uvm_mutex_lock(&g_uvm_global.global_lock);
    src=uvm_gpu_get_by_uuid(&source_uuid);
    dst=uvm_gpu_get_by_uuid(&destination_uuid);
    if (!cask_phys_gpu(src,source_index) || !cask_phys_gpu(dst,destination_index) ||
        src->parent==dst->parent || !uvm_gpu_peer_ref_count(src,dst) ||
        uvm_parent_gpu_peer_link_type(src->parent,dst->parent)!=UVM_GPU_LINK_PCIE_BAR1) {
        status=NV_ERR_NOT_SUPPORTED;
    }
    else {
        status=uvm_gpu_cask_retain_existing_bar1_peer(src,dst);
        if (status==NV_OK) {
            peer_retained=true;cask_phys_held_peer=true;
            cask_phys_held_gpus[0]=src;cask_phys_held_gpus[1]=dst;
        }
    }
    uvm_mutex_unlock(&g_uvm_global.global_lock);
    if (status!=NV_OK) goto unlock_serial;
    requester=pull?dst:src;
    remote=pull?src:dst;
    stage="va_space_identity";
    uvm_va_space_down_write(space);
    if (uvm_va_space_get_gpu_by_uuid_with_gpu_va_space(space,&source_uuid)!=src ||
        uvm_va_space_get_gpu_by_uuid_with_gpu_va_space(space,&destination_uuid)!=dst) {
        status=NV_ERR_INVALID_DEVICE;goto unlock_space;
    }
    stage="gpu_policy";
    if (!cask_phys_gpu(src,source_index) || !cask_phys_gpu(dst,destination_index) ||
        src->parent==dst->parent || !uvm_va_space_peer_enabled(space,src,dst) ||
        g_uvm_global.conf_computing_enabled ||
        uvm_parent_gpu_is_virt_mode_sriov_heavy(src->parent) ||
        uvm_parent_gpu_is_virt_mode_sriov_heavy(dst->parent) ||
        !requester->parent->ce_phys_vidmem_write_supported ||
        requester->parent->dma_addressable_start!=0) {status=NV_ERR_NOT_SUPPORTED;goto unlock_space;}
    stage="ce_class";
    p->ce_class=requester->parent->rm_info.ceClass;
    if (p->ce_class!=AMPERE_DMA_COPY_B) {status=NV_ERR_NOT_SUPPORTED;goto unlock_space;}
    stage="requester_gpu_va_space";
    requester_space=uvm_gpu_va_space_get(space,requester);
    if (!requester_space) {status=NV_ERR_INVALID_STATE;goto unlock_space;}
    stage="map_source";
    status=cask_phys_map(space,requester,src,p->source_va,&src_map,&src_offset,p->request_id,
                         pull?"source_peer":"source_local");
    if (status!=NV_OK) goto unlock_space;
    stage="map_destination";
    status=cask_phys_map(space,requester,dst,p->destination_va,&dst_map,&dst_offset,p->request_id,
                         pull?"destination_local":"destination_peer");
    if (status!=NV_OK) goto unlock_space;
    stage="map_remote_owner";
    status=cask_phys_map(space,remote,remote,pull?p->source_va:p->destination_va,
                         &remote_owner_map,&owner_offset,p->request_id,
                         pull?"source_owner":"destination_owner");
    if (status!=NV_OK) goto unlock_space;
    remote_map=pull?src_map:dst_map;
    remote_offset=pull?src_offset:dst_offset;
    stage="same_remote_allocation";
    if (remote_map->cask_phys_user_client!=remote_owner_map->cask_phys_user_client ||
        remote_map->cask_phys_user_object!=remote_owner_map->cask_phys_user_object ||
        remote_offset!=owner_offset ||
        remote_map->cask_phys_allocation_size!=remote_owner_map->cask_phys_allocation_size ||
        src_map->mem_handle==dst_map->mem_handle) {status=NV_ERR_INVALID_STATE;goto unlock_space;}
    p->source_allocation_offset=src_offset;p->destination_allocation_offset=dst_offset;
    p->source_rm_handle=src_map->mem_handle->rm_handle;p->destination_rm_handle=dst_map->mem_handle->rm_handle;
    p->result_flags=CASK_PHYS_CE_VALIDATED;
    if (p->operation==CASK_PHYS_CE_VALIDATE) {status=NV_OK;goto unlock_space;}
    /* Both RM handles are requester-context duplicates. Query those in exactly
     * that GPU VA space; never reuse the remote owner's physical VRAM address. */
    stage="query_source_rw";
    status=cask_phys_query(requester_space,src_map,src_offset,&p->source_physical,p->request_id,
                           pull?"source_peer":"source_local");
    if (status!=NV_OK) goto unlock_space;
    stage="query_destination_rw";
    status=cask_phys_query(requester_space,dst_map,dst_offset,&p->destination_physical,p->request_id,
                           pull?"destination_local":"destination_peer");
    if (status!=NV_OK) goto unlock_space;
    stage="physical_bounds";
    local_pa=pull?p->destination_physical:p->source_physical;
    remote_pa=pull?p->source_physical:p->destination_physical;
    bar=pci_resource_start(remote->parent->pci_dev,1);bar_size=pci_resource_len(remote->parent->pci_dev,1);
    if (requester->mem_info.max_allocatable_address<3 ||
        local_pa>requester->mem_info.max_allocatable_address-3 ||
        bar_size<4 || bar>NV_U64_MAX-bar_size || remote_pa<bar ||
        remote_pa>bar+bar_size-4 ||
        requester->parent->dma_addressable_limit<3 ||
        remote_pa>requester->parent->dma_addressable_limit-3) {status=NV_ERR_INVALID_ADDRESS;goto unlock_space;}
    remote_aperture=p->remote_phys_mode==CASK_PHYS_CE_REMOTE_COHERENT?
                    UVM_APERTURE_SYS:UVM_APERTURE_SYS_NON_COHERENT;
    p->source_is_peer=uvm_gpu_address_is_peer(requester,
        uvm_gpu_address_physical(pull?remote_aperture:UVM_APERTURE_VID,p->source_physical));
    p->destination_is_peer=uvm_gpu_address_is_peer(requester,
        uvm_gpu_address_physical(pull?UVM_APERTURE_VID:remote_aperture,p->destination_physical));
    /* Exact C7B5/Turing source-only guard prediction, not a call to its normal
     * memcopy path. Dynamic BAR1 ranges may not be known to the classifier.
     * False therefore does not establish vendor support for this raw PULL. */
    p->stock_rejects_peer_source=p->source_is_peer;
    pr_info("CASKPHYS request=%llu stage=classification executor=%s transfer=%s src_is_peer=%u dst_is_peer=%u stock_rejects_peer_source=%u stock_hal_unchanged=1 vendor_peer_read_support_established=0\n",
        p->request_id,cask_phys_bdf(requester),pull?"PULL":"PUSH",p->source_is_peer,
        p->destination_is_peer,p->stock_rejects_peer_source);
    if ((pull?p->destination_is_peer:p->source_is_peer)!=0) {status=NV_ERR_INVALID_STATE;goto unlock_space;}
    /* Extra holds protect all three duped objects if completion is uncertain. */
    cask_phys_held_maps[0]=src_map->mem_handle;cask_phys_held_maps[1]=dst_map->mem_handle;
    cask_phys_held_maps[2]=remote_owner_map->mem_handle;
    for(j=0;j<3;++j) nv_kref_get(&cask_phys_held_maps[j]->ref_count);
    retained=true;
    stage="channel_begin";
    status=uvm_push_begin_gpu_to_gpu(requester->channel_manager,remote,push,"CaskLogic physical CE request %llu",p->request_id);
    if (status!=NV_OK) goto unlock_space;
    stage="channel_policy";
    if (!uvm_channel_is_p2p(push->channel) || !uvm_channel_is_privileged(push->channel) ||
        uvm_channel_is_proxy(push->channel) || !uvm_channel_is_ce(push->channel) ||
        uvm_channel_get_gpu(push->channel)!=requester) {
        /* Even an empty push must complete before references can be released. */
        inflight=true;uvm_push_end(push);status=uvm_push_wait(push);
        if (status==NV_OK) {inflight=false;status=NV_ERR_NOT_SUPPORTED;}
        goto unlock_space;
    }
    p->result_flags|=CASK_PHYS_CE_P2P_CHANNEL|CASK_PHYS_CE_PRIVILEGED|CASK_PHYS_CE_NO_VIRTUAL_FALLBACK;
    /* These method values are defined by clc7b5.h. No generic peer-aperture
     * PEERMEM3 is used with a BAR1 address, and arbitrary mode bits are rejected.
     * SYS_COH/SYS_NONCOH names do not prove different PCIe transaction attrs. */
    p->source_phys_mode=pull?p->remote_phys_mode:HWCONST(C7B5,SET_SRC_PHYS_MODE,TARGET,LOCAL_FB);
    p->destination_phys_mode=pull?HWCONST(C7B5,SET_DST_PHYS_MODE,TARGET,LOCAL_FB):p->remote_phys_mode;
    plc=requester->parent->ce_hal->plc_mode();
    p->launch_dma=HWCONST(C7B5,LAUNCH_DMA,SRC_MEMORY_LAYOUT,PITCH)|
        HWCONST(C7B5,LAUNCH_DMA,DST_MEMORY_LAYOUT,PITCH)|HWCONST(C7B5,LAUNCH_DMA,MULTI_LINE_ENABLE,FALSE)|
        HWCONST(C7B5,LAUNCH_DMA,REMAP_ENABLE,FALSE)|HWCONST(C7B5,LAUNCH_DMA,FLUSH_ENABLE,TRUE)|
        HWCONST(C7B5,LAUNCH_DMA,FLUSH_TYPE,SYS)|HWCONST(C7B5,LAUNCH_DMA,SRC_TYPE,PHYSICAL)|
        HWCONST(C7B5,LAUNCH_DMA,DST_TYPE,PHYSICAL)|HWCONST(C7B5,LAUNCH_DMA,DATA_TRANSFER_TYPE,NON_PIPELINED)|plc;
    pr_info("CASKPHYS request=%llu stage=methods transfer=%s executor=%s src=%s dst=%s src_va=%llx dst_va=%llx src_mem=%x dst_mem=%x src_off=%llx dst_off=%llx src_phys=%llx dst_phys=%llx bytes=4 class=%x channel=%s p2p=1 privileged=1 src_mode=%x dst_mode=%x launch=%x no_virtual_fallback=1\n",
        p->request_id,pull?"PULL":"PUSH",cask_phys_bdf(requester),uvm_gpu_name(src),uvm_gpu_name(dst),
        p->source_va,p->destination_va,p->source_rm_handle,p->destination_rm_handle,src_offset,dst_offset,
        p->source_physical,p->destination_physical,p->ce_class,push->channel->name,
        p->source_phys_mode,p->destination_phys_mode,p->launch_dma);
    pr_info("CASKPHYS request=%llu stage=dma_range executor=%s remote=%s dma_start=%llx dma_limit=%llx remote_bar1=%llx remote_bar1_size=%llx local_vram_limit=%llx peer_reference_held=1\n",
        p->request_id,cask_phys_bdf(requester),cask_phys_bdf(remote),requester->parent->dma_addressable_start,
        requester->parent->dma_addressable_limit,bar,bar_size,requester->mem_info.max_allocatable_address);
    /* UVM exposes the shared CE subchannel under C6B5, not C7B5.
     * This is only the pushbuffer routing token: the admitted hardware class
     * and payload encodings above remain C7B5. Pin all emitted offsets. */
    BUILD_BUG_ON(NVC6B5_SET_SRC_PHYS_MODE != NVC7B5_SET_SRC_PHYS_MODE);
    BUILD_BUG_ON(NVC6B5_SET_DST_PHYS_MODE != NVC7B5_SET_DST_PHYS_MODE);
    BUILD_BUG_ON(NVC6B5_LINE_LENGTH_IN != NVC7B5_LINE_LENGTH_IN);
    BUILD_BUG_ON(NVC6B5_LAUNCH_DMA != NVC7B5_LAUNCH_DMA);
    NV_PUSH_2U(C6B5,SET_SRC_PHYS_MODE,p->source_phys_mode,SET_DST_PHYS_MODE,p->destination_phys_mode);
    requester->parent->ce_hal->offset_in_out(push,p->source_physical,p->destination_physical);
    NV_PUSH_1U(C6B5,LINE_LENGTH_IN,4);
    NV_PUSH_1U(C6B5,LAUNCH_DMA,p->launch_dma);
    stage="submitted_wait";
    p->result_flags|=CASK_PHYS_CE_SUBMITTED;
    inflight=true;uvm_push_end(push);status=uvm_push_wait(push);
    if (status==NV_OK) {inflight=false;p->result_flags|=CASK_PHYS_CE_COMPLETED;}
unlock_space:
    if (retained && inflight) {
        cask_phys_fatal=true;__module_get(THIS_MODULE);p->result_flags|=CASK_PHYS_CE_RETAINED;
        pr_err("CASKPHYS request=%llu completion_unconfirmed status=%x objects_retained_until_reboot=1\n",p->request_id,status);
    }
    else if (retained) {
        for(j=0;j<3;++j) {nv_kref_put(&cask_phys_held_maps[j]->ref_count,uvm_release_rm_handle);cask_phys_held_maps[j]=NULL;}
    }
    pr_info("CASKPHYS request=%llu stage=return operation=%u transfer=%u status=%x flags=%x last_stage=%s\n",
            p->request_id,p->operation,p->transfer,status,p->result_flags,stage);
    uvm_va_space_up_write(space);
    if (peer_retained && !inflight) {
        uvm_mutex_lock(&g_uvm_global.global_lock);
        uvm_gpu_cask_release_bar1_peer(src,dst);
        uvm_mutex_unlock(&g_uvm_global.global_lock);
        cask_phys_held_gpus[0]=NULL;cask_phys_held_gpus[1]=NULL;cask_phys_held_peer=false;
    }
unlock_serial:
    mutex_unlock(&cask_phys_serial);
    return status;
}
