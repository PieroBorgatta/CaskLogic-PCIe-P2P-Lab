/* Included only by uvm_map_external.c, after its existing functions.
 * Diagnostic only:4 bytes, current CUDA VA-space, exact two native GPUs.
 * Never accepts a user physical address or derives one from a log.
 */
#include "uvm_test.h"
#include "uvm_channel.h"
#include "uvm_push_macros.h"
#include "clc6b5.h"
#include "clc7b5.h"
#include <linux/capability.h>
#include <linux/module.h>
#include <linux/pci.h>
#include <asm/processor.h>
#include <asm/cpufeature.h>

static bool uvm_cask_physical_ce;
module_param(uvm_cask_physical_ce, bool, 0400);
MODULE_PARM_DESC(uvm_cask_physical_ce, "Native CaskLogic4-byte privileged physical CE diagnostic; default off");
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
        {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01},
        {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x02}
    };
    if (!memcmp(uuid,ids[0],16)) return 0;
    if (!memcmp(uuid,ids[1],16)) return 1;
    return -1;
}

static NV_STATUS cask_phys_map(uvm_va_space_t *space, uvm_gpu_t *requester,
                              uvm_gpu_t *owner, NvU64 va,
                              uvm_ext_gpu_map_t **out, NvU64 *offset)
{
    uvm_va_range_external_t *range=uvm_va_range_external_find(space,va);
    uvm_ext_gpu_map_t *map;
    NvU64 delta;
    if (!range || va>NV_U64_MAX-3 || range->va_range.node.end<va+3)
        return NV_ERR_INVALID_ADDRESS;
    map=uvm_va_range_ext_gpu_map(range,requester,va);
    if (!map || !map->mem_handle || !map->mem_handle->rm_handle ||
        map->gpu!=requester || map->mem_handle->gpu!=requester ||
        map->owning_gpu!=owner || map->is_sysmem || map->is_egm ||
        !map->cask_phys_recorded || !map->cask_phys_device_descendant ||
        map->cask_phys_kind!=0 || map->cask_phys_format!=UvmGpuFormatTypeDefault ||
        map->cask_phys_page_size<4096 || map->cask_phys_page_size%4096 ||
        map->node.start!=map->cask_phys_origin_start ||
        map->node.end!=map->cask_phys_origin_end || map->node.end<va+3 ||
        (map->cask_phys_mapping_type!=UvmGpuMappingTypeReadWrite &&
         map->cask_phys_mapping_type!=UvmGpuMappingTypeReadWriteAtomic))
        return NV_ERR_INVALID_STATE;
    /* Reject split/rebound aliases. Metadata came from successful RM duplication. */
    delta=va-map->cask_phys_origin_start;
    if (delta>NV_U64_MAX-map->cask_phys_map_offset)
        return NV_ERR_INVALID_LIMIT;
    *offset=map->cask_phys_map_offset+delta;
    if (*offset>map->cask_phys_allocation_size ||
        map->cask_phys_allocation_size-*offset<4 ||
        (*offset&3) || (*offset&4095)>4092 ||
        map->cask_phys_allocation_size-(*offset&~4095ULL)<4096)
        return NV_ERR_INVALID_LIMIT;
    *out=map;
    return uvm_tracker_wait(&map->tracker);
}

static NV_STATUS cask_phys_query(uvm_gpu_va_space_t *gpu_space,
                                uvm_ext_gpu_map_t *map, NvU64 offset, NvU64 *pa)
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
    uvm_gpu_t *src=NULL,*dst=NULL;
    uvm_gpu_va_space_t *src_space;
    uvm_ext_gpu_map_t *src_map=NULL,*dst_map=NULL,*dst_owner_map=NULL;
    NvU64 src_offset=0,dst_offset=0,owner_offset=0,bar,bar_size;
    uvm_push_t push_storage;
    uvm_push_t *push=&push_storage;
    NV_STATUS status=NV_ERR_INVALID_ARGUMENT;
    bool retained=false,inflight=false,peer_retained=false;
    int source_index,destination_index,j;
    NvU32 plc;
    BUILD_BUG_ON(sizeof(*p)!=144);
    BUILD_BUG_ON(UVM_TEST_CASK_PHYSICAL_CE!=CASK_PHYS_CE_IOCTL);
    BUILD_BUG_ON(offsetof(UVM_TEST_CASK_PHYSICAL_CE_PARAMS,source_va)!=48);
    BUILD_BUG_ON(offsetof(UVM_TEST_CASK_PHYSICAL_CE_PARAMS,source_physical)!=72);
    BUILD_BUG_ON(offsetof(UVM_TEST_CASK_PHYSICAL_CE_PARAMS,result_flags)!=128);
    memset(&p->source_physical,0,sizeof(*p)-offsetof(UVM_TEST_CASK_PHYSICAL_CE_PARAMS,source_physical));
    if (!uvm_cask_physical_ce || !capable(CAP_SYS_ADMIN)) return NV_ERR_INSUFFICIENT_PERMISSIONS;
    if (boot_cpu_data.x86_vendor!=X86_VENDOR_INTEL || boot_cpu_data.x86!=6 ||
        boot_cpu_data.x86_model!=0x9a || boot_cpu_data.x86_stepping!=3 || boot_cpu_has(X86_FEATURE_HYPERVISOR))
        return NV_ERR_NOT_SUPPORTED;
    if (p->abi_version!=CASK_PHYS_CE_ABI || p->operation>CASK_PHYS_CE_EXECUTE ||
        !p->request_id || p->bytes!=4 || p->reserved || (p->source_va&3) ||
        (p->destination_va&3) || p->source_va==p->destination_va)
        return NV_ERR_INVALID_ARGUMENT;
    source_index=cask_phys_identity(p->source_uuid);
    destination_index=cask_phys_identity(p->destination_uuid);
    if (source_index<0 || destination_index<0 || source_index==destination_index)
        return NV_ERR_INVALID_DEVICE;
    memcpy(&source_uuid,p->source_uuid,16);memcpy(&destination_uuid,p->destination_uuid,16);
    mutex_lock(&cask_phys_serial);
    if (cask_phys_fatal) {status=NV_ERR_INVALID_STATE;goto unlock_serial;}
    /* Never take global_lock while holding the VA lock. Retain an existing
     * pairing first, then verify that it belongs to this caller's VA space.
     * No new peer pair is created by this diagnostic. */
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
    uvm_va_space_down_write(space);
    if (uvm_va_space_get_gpu_by_uuid_with_gpu_va_space(space,&source_uuid)!=src ||
        uvm_va_space_get_gpu_by_uuid_with_gpu_va_space(space,&destination_uuid)!=dst) {
        status=NV_ERR_INVALID_DEVICE;goto unlock_space;
    }
    if (!cask_phys_gpu(src,source_index) || !cask_phys_gpu(dst,destination_index) ||
        src->parent==dst->parent || !uvm_va_space_peer_enabled(space,src,dst) ||
        g_uvm_global.conf_computing_enabled ||
        uvm_parent_gpu_is_virt_mode_sriov_heavy(src->parent) ||
        uvm_parent_gpu_is_virt_mode_sriov_heavy(dst->parent) ||
        !src->parent->ce_phys_vidmem_write_supported ||
        src->parent->dma_addressable_start!=0) {status=NV_ERR_NOT_SUPPORTED;goto unlock_space;}
    p->ce_class=src->parent->rm_info.ceClass;
    if (p->ce_class!=AMPERE_DMA_COPY_A && p->ce_class!=AMPERE_DMA_COPY_B) {
        status=NV_ERR_NOT_SUPPORTED;goto unlock_space;
    }
    src_space=uvm_gpu_va_space_get(space,src);
    if (!src_space) {status=NV_ERR_INVALID_STATE;goto unlock_space;}
    status=cask_phys_map(space,src,src,p->source_va,&src_map,&src_offset);
    if (status!=NV_OK) goto unlock_space;
    status=cask_phys_map(space,src,dst,p->destination_va,&dst_map,&dst_offset);
    if (status!=NV_OK) goto unlock_space;
    status=cask_phys_map(space,dst,dst,p->destination_va,&dst_owner_map,&owner_offset);
    if (status!=NV_OK) goto unlock_space;
    if (dst_map->cask_phys_user_client!=dst_owner_map->cask_phys_user_client ||
        dst_map->cask_phys_user_object!=dst_owner_map->cask_phys_user_object ||
        dst_offset!=owner_offset ||
        dst_map->cask_phys_allocation_size!=dst_owner_map->cask_phys_allocation_size ||
        src_map->mem_handle==dst_map->mem_handle) {status=NV_ERR_INVALID_STATE;goto unlock_space;}
    p->source_allocation_offset=src_offset;p->destination_allocation_offset=dst_offset;
    p->source_rm_handle=src_map->mem_handle->rm_handle;p->destination_rm_handle=dst_map->mem_handle->rm_handle;
    p->result_flags=CASK_PHYS_CE_VALIDATED;
    if (p->operation==CASK_PHYS_CE_VALIDATE) {status=NV_OK;goto unlock_space;}
    status=cask_phys_query(src_space,src_map,src_offset,&p->source_physical);
    if (status!=NV_OK) goto unlock_space;
    status=cask_phys_query(src_space,dst_map,dst_offset,&p->destination_physical);
    if (status!=NV_OK) goto unlock_space;
    bar=pci_resource_start(dst->parent->pci_dev,1);bar_size=pci_resource_len(dst->parent->pci_dev,1);
    if (src->mem_info.max_allocatable_address<3 ||
        p->source_physical>src->mem_info.max_allocatable_address-3 ||
        bar_size<4 || bar>NV_U64_MAX-bar_size || p->destination_physical<bar ||
        p->destination_physical>bar+bar_size-4 ||
        src->parent->dma_addressable_limit<3 ||
        p->destination_physical>src->parent->dma_addressable_limit-3) {status=NV_ERR_INVALID_ADDRESS;goto unlock_space;}
    /* Extra holds protect exactly these duped objects even if completion fails. */
    cask_phys_held_maps[0]=src_map->mem_handle;cask_phys_held_maps[1]=dst_map->mem_handle;
    cask_phys_held_maps[2]=dst_owner_map->mem_handle;
    for(j=0;j<3;++j) nv_kref_get(&cask_phys_held_maps[j]->ref_count);
    retained=true;
    status=uvm_push_begin_gpu_to_gpu(src->channel_manager,dst,push,"CaskLogic physical CE request %llu",p->request_id);
    if (status!=NV_OK) goto unlock_space;
    if (!uvm_channel_is_p2p(push->channel) || !uvm_channel_is_privileged(push->channel) ||
        uvm_channel_is_proxy(push->channel) || !uvm_channel_is_ce(push->channel)) {
        /* Even an empty push must complete before references can be released. */
        inflight=true;uvm_push_end(push);status=uvm_push_wait(push);
        if (status==NV_OK) {inflight=false;status=NV_ERR_NOT_SUPPORTED;}
        goto unlock_space;
    }
    p->result_flags|=CASK_PHYS_CE_P2P_CHANNEL|CASK_PHYS_CE_PRIVILEGED|CASK_PHYS_CE_NO_VIRTUAL_FALLBACK;
    p->source_phys_mode=HWCONST(C6B5,SET_SRC_PHYS_MODE,TARGET,LOCAL_FB);
    /* Explicit SYS_NONCOHERENT matches the earlier external PTE aperture.
     * Stock UVM's UVM_APERTURE_SYS CE helper instead selects COHERENT_SYSMEM.
     * This tests this exact physical transaction; it is not a claim that only
     * virtual translation differs from every CUDA CE operation. */
    p->destination_phys_mode=HWCONST(C6B5,SET_DST_PHYS_MODE,TARGET,NONCOHERENT_SYSMEM);
    plc=src->parent->ce_hal->plc_mode();
    p->launch_dma=HWCONST(C6B5,LAUNCH_DMA,SRC_MEMORY_LAYOUT,PITCH)|
        HWCONST(C6B5,LAUNCH_DMA,DST_MEMORY_LAYOUT,PITCH)|HWCONST(C6B5,LAUNCH_DMA,MULTI_LINE_ENABLE,FALSE)|
        HWCONST(C6B5,LAUNCH_DMA,REMAP_ENABLE,FALSE)|HWCONST(C6B5,LAUNCH_DMA,FLUSH_ENABLE,TRUE)|
        HWCONST(C6B5,LAUNCH_DMA,FLUSH_TYPE,SYS)|HWCONST(C6B5,LAUNCH_DMA,SRC_TYPE,PHYSICAL)|
        HWCONST(C6B5,LAUNCH_DMA,DST_TYPE,PHYSICAL)|HWCONST(C6B5,LAUNCH_DMA,DATA_TRANSFER_TYPE,NON_PIPELINED)|plc;
    pr_info("CASKPHYS request=%llu stage=methods src=%s dst=%s src_va=%llx dst_va=%llx src_mem=%x dst_mem=%x src_off=%llx dst_off=%llx src_phys=%llx dst_phys=%llx bytes=4 class=%x channel=%s p2p=1 privileged=1 src_mode=%x dst_mode=%x launch=%x no_virtual_fallback=1\n",
        p->request_id,uvm_gpu_name(src),uvm_gpu_name(dst),p->source_va,p->destination_va,
        p->source_rm_handle,p->destination_rm_handle,src_offset,dst_offset,p->source_physical,
        p->destination_physical,p->ce_class,push->channel->name,p->source_phys_mode,p->destination_phys_mode,p->launch_dma);
    pr_info("CASKPHYS request=%llu stage=dma_range dma_start=%llx dma_limit=%llx dst_bar1=%llx dst_bar1_size=%llx peer_reference_held=1\n",
        p->request_id,src->parent->dma_addressable_start,src->parent->dma_addressable_limit,bar,bar_size);
    NV_PUSH_2U(C6B5,SET_SRC_PHYS_MODE,p->source_phys_mode,SET_DST_PHYS_MODE,p->destination_phys_mode);
    src->parent->ce_hal->offset_in_out(push,p->source_physical,p->destination_physical);
    NV_PUSH_1U(C6B5,LINE_LENGTH_IN,4);
    NV_PUSH_1U(C6B5,LAUNCH_DMA,p->launch_dma);
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
    pr_info("CASKPHYS request=%llu stage=return operation=%u status=%x flags=%x\n",p->request_id,p->operation,status,p->result_flags);
    uvm_va_space_up_write(space);
    if (peer_retained && !inflight) {
        uvm_mutex_lock(&g_uvm_global.global_lock);
        uvm_gpu_cask_release_bar1_peer(src,dst);
        uvm_mutex_unlock(&g_uvm_global.global_lock);
        cask_phys_held_gpus[0]=NULL;cask_phys_held_gpus[1]=NULL;cask_phys_held_peer=false;
    }
unlock_serial:
    REDACTED
    return status;
}
