/* Isolated native diagnostic. The sole peer read is NV_PMC_BOOT_0=0 in BAR0.
 * dma_map_resource maps that MMIO page read-only in the requester's DMA domain.
 * It never changes the IOMMU domain, peer policy, PCI registers or firmware.
 * Only fresh UVM allocations are written; no peer VA/allocation is mapped.
 */
#include "uvm_mem.h"
#include "uvm_hal.h"
#include "uvm_channel.h"
#include "uvm_push_macros.h"
#include "clc6b5.h"
#include "clc7b5.h"
#include <linux/capability.h>
#include <linux/dma-mapping.h>
#include <linux/iommu.h>
#include <linux/io.h>
#include <linux/pci.h>
#include <linux/vmalloc.h>
#include <asm/cacheflush.h>
#include <asm/processor.h>
#include <asm/cpufeature.h>

static bool uvm_cask_iova_mmio;
module_param(uvm_cask_iova_mmio, bool, 0400);
MODULE_PARM_DESC(uvm_cask_iova_mmio, "Native read-only peer MMIO via DMA API IOVA; default off");
static DEFINE_MUTEX(cask_iova_lock);
static bool cask_iova_used[2], cask_iova_fatal;
/* On uncertain completion, all GPU/buffer/DMA references remain until reboot. */
static uvm_gpu_t *cask_iova_held_gpus[2];
static uvm_mem_t *cask_iova_held_sys, *cask_iova_held_vid;
static dma_addr_t cask_iova_held_dma;

static bool cask_iova_gpu(uvm_gpu_t *gpu, unsigned int index, const NvU8 *uuid)
{
    static const NvU8 expected[2][16] = {
        {0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x01},
        {0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x02}
    };
    struct pci_dev *pci = gpu ? gpu->parent->pci_dev : NULL;
    return index < 2 && !memcmp(uuid, expected[index], 16) && pci &&
        pci_domain_nr(pci->bus) == 0 && pci->vendor == 0x10de &&
        pci->device == (index ? 0x2571 : 0x28b0) &&
        pci->bus->number == (index ? 6 : 1) && pci->devfn == 0;
}

static NV_STATUS cask_iova_wait(uvm_push_t *push, bool *pending)
{
    NV_STATUS status;
    *pending = true;
    uvm_push_end(push);
    status = uvm_push_wait(push);
    if (status == NV_OK)
        *pending = false;
    return status;
}

static NV_STATUS cask_iova_begin(uvm_gpu_t *gpu, uvm_push_t *push, bool *pending)
{
    NV_STATUS status = uvm_push_begin(gpu->channel_manager, UVM_CHANNEL_TYPE_CPU_TO_GPU,
                                      push, "CaskLogic IOVA MMIO read");
    if (status != NV_OK)
        return status;
    if (!uvm_channel_is_privileged(push->channel) || uvm_channel_is_proxy(push->channel) ||
        !uvm_channel_is_ce(push->channel) || uvm_channel_is_p2p(push->channel) ||
        uvm_channel_get_gpu(push->channel) != gpu) {
        status = cask_iova_wait(push, pending);
        return status == NV_OK ? NV_ERR_NOT_SUPPORTED : status;
    }
    return NV_OK;
}

static NvU32 cask_iova_launch(uvm_gpu_t *gpu)
{
    return HWCONST(C7B5,LAUNCH_DMA,SRC_MEMORY_LAYOUT,PITCH)|
        HWCONST(C7B5,LAUNCH_DMA,DST_MEMORY_LAYOUT,PITCH)|HWCONST(C7B5,LAUNCH_DMA,MULTI_LINE_ENABLE,FALSE)|
        HWCONST(C7B5,LAUNCH_DMA,REMAP_ENABLE,FALSE)|HWCONST(C7B5,LAUNCH_DMA,FLUSH_ENABLE,TRUE)|
        HWCONST(C7B5,LAUNCH_DMA,FLUSH_TYPE,SYS)|HWCONST(C7B5,LAUNCH_DMA,SRC_TYPE,PHYSICAL)|
        HWCONST(C7B5,LAUNCH_DMA,DST_TYPE,PHYSICAL)|HWCONST(C7B5,LAUNCH_DMA,DATA_TRANSFER_TYPE,NON_PIPELINED)|
        gpu->parent->ce_hal->plc_mode();
}

static NV_STATUS cask_iova_one(uvm_gpu_t *gpu, uvm_gpu_address_t vid,
                               uvm_gpu_address_t readback_va, NvU32 *readback,
                               NvU64 source, NvU32 expected, NvU32 mode,
                               unsigned int seq, UVM_TEST_CASK_IOVA_MMIO_PARAMS *p,
                               bool *pending)
{
    uvm_push_t storage, *push = &storage;
    NvU32 sentinel = ~expected, i, bad = 0, guards = 0;
    NV_STATUS status = cask_iova_begin(gpu, push, pending);
    if (status != NV_OK)
        return status;
    gpu->parent->ce_hal->memset_4(push, vid, sentinel, PAGE_SIZE);
    gpu->parent->ce_hal->memcopy(push, readback_va, vid, PAGE_SIZE);
    status = cask_iova_wait(push, pending);
    if (status != NV_OK)
        return status;
    for (i = 0; i < PAGE_SIZE / sizeof(*readback); ++i)
        bad += READ_ONCE(readback[i]) != sentinel;
    if (bad)
        return NV_ERR_INVALID_STATE;
    status = cask_iova_begin(gpu, push, pending);
    if (status != NV_OK)
        return status;
    BUILD_BUG_ON(NVC6B5_SET_SRC_PHYS_MODE != NVC7B5_SET_SRC_PHYS_MODE);
    BUILD_BUG_ON(NVC6B5_SET_DST_PHYS_MODE != NVC7B5_SET_DST_PHYS_MODE);
    BUILD_BUG_ON(NVC6B5_LINE_LENGTH_IN != NVC7B5_LINE_LENGTH_IN);
    BUILD_BUG_ON(NVC6B5_LAUNCH_DMA != NVC7B5_LAUNCH_DMA);
    NV_PUSH_2U(C6B5,SET_SRC_PHYS_MODE,mode,SET_DST_PHYS_MODE,0);
    gpu->parent->ce_hal->offset_in_out(push, source, vid.address);
    NV_PUSH_1U(C6B5,LINE_LENGTH_IN,4);
    NV_PUSH_1U(C6B5,LAUNCH_DMA,cask_iova_launch(gpu));
    p->result_flags |= CASK_IOVA_SUBMITTED;
    status = cask_iova_wait(push, pending);
    if (status != NV_OK)
        return status;
    status = cask_iova_begin(gpu, push, pending);
    if (status != NV_OK)
        return status;
    gpu->parent->ce_hal->memcopy(push, readback_va, vid, PAGE_SIZE);
    status = cask_iova_wait(push, pending);
    if (status != NV_OK)
        return status;
    for (i = 1; i < PAGE_SIZE / sizeof(*readback); ++i)
        guards += READ_ONCE(readback[i]) != sentinel;
    pr_info("CASKIOVA request=%llu index=%u stage=result seq=%u mode=%u kind=%s source_iova=%llx bytes=4 expected=%08x actual=%08x sentinel=%08x match=%u guard_changed=%u baseline_valid=1 checked_words=%lu class=c7b5 launch=%x p2p_channel=0 privileged=1\n",
        p->request_id,p->index,seq,mode,seq%3==1 ? "peer_bar0" : "host_ram",source,
        expected,READ_ONCE(readback[0]),sentinel,READ_ONCE(readback[0])==expected,guards,
        PAGE_SIZE / sizeof(*readback),cask_iova_launch(gpu));
    p->completed_mask |= 1U << seq;
    if (guards)
        return NV_ERR_INVALID_STATE;
    if (seq%3==1) {
        if (READ_ONCE(readback[0]) == expected)
            p->peer_pass_mask |= 1U << (mode-1);
    }
    else {
        if (READ_ONCE(readback[0]) != expected)
            return NV_ERR_INVALID_STATE;
        p->host_pass_mask |= 1U << seq;
    }
    return NV_OK;
}

NV_STATUS uvm_test_cask_iova_mmio(UVM_TEST_CASK_IOVA_MMIO_PARAMS *p, struct file *filp)
{
    uvm_va_space_t *space = uvm_va_space_get(filp);
    uvm_gpu_t *gpus[2] = {NULL,NULL}, *gpu;
    NvProcessorUuid uuid;
    struct device *dev;
    struct pci_dev *peer;
    struct iommu_domain *domain;
    uvm_mem_t *sys = NULL, *vid = NULL;
    uvm_gpu_address_t sys_dma, local_vid, readback_va;
    NvU32 *cpu, *readback, expected, after, i, mode, seq, source_changed = 0;
    phys_addr_t host_phys, translated;
    resource_size_t bar;
    dma_addr_t iova = 0;
    void __iomem *mmio = NULL;
    bool pending = false, mapped = false, held = false;
    NV_STATUS status = NV_ERR_INVALID_ARGUMENT;
    const char *phase = "entry";
    BUILD_BUG_ON(sizeof(*p) != 96);
    BUILD_BUG_ON(UVM_TEST_CASK_IOVA_MMIO != CASK_IOVA_IOCTL);
    p->mmio_iova=0;p->mmio_physical=0;p->domain_type=0;p->host_pass_mask=0;
    p->peer_pass_mask=0;p->completed_mask=0;p->result_flags=0;p->rmStatus=0;
    if (!uvm_cask_iova_mmio || !capable(CAP_SYS_ADMIN))
        return NV_ERR_INSUFFICIENT_PERMISSIONS;
    if (p->abi_version != CASK_IOVA_ABI || p->operation > 1 || p->index > 1 || p->reserved || !p->request_id)
        return NV_ERR_INVALID_ARGUMENT;
    if (boot_cpu_data.x86_vendor != X86_VENDOR_INTEL || boot_cpu_data.x86 != 6 ||
        boot_cpu_data.x86_model != 0x9a || boot_cpu_data.x86_stepping != 3 ||
        boot_cpu_has(X86_FEATURE_HYPERVISOR) || g_uvm_global.conf_computing_enabled)
        return NV_ERR_NOT_SUPPORTED;
    mutex_lock(&cask_iova_lock);
    if (cask_iova_fatal) {status=NV_ERR_INVALID_STATE;goto unlock;}
    uvm_mutex_lock(&g_uvm_global.global_lock);
    for (i=0;i<2;++i) {
        memcpy(&uuid,p->gpu_uuid[i],16);
        gpus[i]=uvm_gpu_get_by_uuid(&uuid);
        if (!cask_iova_gpu(gpus[i],i,p->gpu_uuid[i]))
            break;
    }
    if (i==2) {
        uvm_gpu_retain(gpus[0]);uvm_gpu_retain(gpus[1]);held=true;
    }
    uvm_mutex_unlock(&g_uvm_global.global_lock);
    if (!held) {status=NV_ERR_INVALID_DEVICE;goto unlock;}
    gpu=gpus[p->index];peer=gpus[1-p->index]->parent->pci_dev;dev=&gpu->parent->pci_dev->dev;
    uvm_va_space_down_read_rm(space);
    for(i=0;i<2;++i) {
        memcpy(&uuid,p->gpu_uuid[i],16);
        if(uvm_va_space_get_gpu_by_uuid_with_gpu_va_space(space,&uuid)!=gpus[i]) {
            status=NV_ERR_INVALID_DEVICE;goto done;
        }
    }
    phase="domain";
    domain=iommu_get_domain_for_dev(dev);
    if (!domain || domain->type!=IOMMU_DOMAIN_DMA || gpu->parent->rm_info.ceClass!=AMPERE_DMA_COPY_B ||
        !gpu->parent->ce_phys_vidmem_write_supported || gpu->parent->dma_addressable_start!=0) {
        status=NV_ERR_NOT_SUPPORTED;goto done;
    }
    p->domain_type=domain->type;p->result_flags=CASK_IOVA_VALIDATED;
    if (!p->operation) {status=NV_OK;goto done;}
    if (cask_iova_used[p->index]) {status=NV_ERR_INVALID_STATE;goto done;}
    cask_iova_used[p->index]=true;
    bar=pci_resource_start(peer,0);
    if (!bar || (bar&(PAGE_SIZE-1)) || pci_resource_len(peer,0)<PAGE_SIZE ||
        !(pci_resource_flags(peer,0)&IORESOURCE_MEM) || (pci_resource_flags(peer,0)&IORESOURCE_PREFETCH)) {
        status=NV_ERR_INVALID_ADDRESS;goto done;
    }
    phase="cpu_reference";
    mmio=pci_iomap_range(peer,0,0,4);
    if (!mmio) {status=NV_ERR_NO_MEMORY;goto done;}
    expected=ioread32(mmio);
    if (expected!=(p->index ? 0x197000a1U : 0xb76000a1U)) {status=NV_ERR_GPU_IS_LOST;goto done;}
    phase="dma_map_resource";
    iova=dma_map_resource(dev,bar,PAGE_SIZE,DMA_TO_DEVICE,0);
    if (dma_mapping_error(dev,iova)) {status=NV_ERR_NO_MEMORY;goto done;}
    mapped=true;translated=iommu_iova_to_phys(domain,iova);
    p->mmio_iova=iova;p->mmio_physical=bar;
    pr_info("CASKIOVA request=%llu index=%u stage=mapping executor=%s peer=%s domain_type=%u iova=%llx physical=%llx translated=%llx bytes=%lu direction=DMA_TO_DEVICE source_register=NV_PMC_BOOT_0 offset=0 expected=%08x\n",
        p->request_id,p->index,pci_name(gpu->parent->pci_dev),pci_name(peer),domain->type,
        (NvU64)iova,(NvU64)bar,(NvU64)translated,PAGE_SIZE,expected);
    if (!iova || iova==bar || translated!=bar ||
        gpu->parent->dma_addressable_limit<PAGE_SIZE-1 || iova>gpu->parent->dma_addressable_limit-(PAGE_SIZE-1)) {
        status=NV_ERR_INVALID_ADDRESS;goto done;
    }
    phase="allocations";
    status=uvm_mem_alloc_sysmem_and_map_cpu_kernel(2*PAGE_SIZE,current->mm,&sys);
    if (status!=NV_OK) goto done;
    status=uvm_mem_alloc_vidmem(PAGE_SIZE,gpu,&vid);
    if (status!=NV_OK) goto done;
    status=uvm_mem_map_gpu_kernel(sys,gpu);
    if (status!=NV_OK) goto done;
    status=uvm_mem_map_gpu_kernel(vid,gpu);
    if (status!=NV_OK) goto done;
    cpu=uvm_mem_get_cpu_addr_kernel(sys);readback=(NvU32 *)((char *)cpu+PAGE_SIZE);
    sys_dma=uvm_mem_gpu_address_physical(sys,gpu,0,4);
    local_vid=uvm_mem_gpu_address_physical(vid,gpu,0,PAGE_SIZE);
    readback_va=uvm_mem_gpu_address_virtual_kernel(sys,gpu);readback_va.address+=PAGE_SIZE;
    if (!is_vmalloc_addr(cpu) || !vmalloc_to_page(cpu) || sys_dma.is_virtual || local_vid.is_virtual ||
        sys_dma.aperture!=UVM_APERTURE_SYS || local_vid.aperture!=UVM_APERTURE_VID) {
        status=NV_ERR_INVALID_STATE;goto done;
    }
    host_phys=page_to_phys(vmalloc_to_page(cpu));translated=iommu_iova_to_phys(domain,sys_dma.address);
    if (translated!=host_phys || !sys_dma.address || (sys_dma.address&3) ||
        gpu->mem_info.max_allocatable_address<PAGE_SIZE-1 ||
        local_vid.address>gpu->mem_info.max_allocatable_address-(PAGE_SIZE-1)) {
        status=NV_ERR_INVALID_ADDRESS;goto done;
    }
    pr_info("CASKIOVA request=%llu index=%u stage=host_mapping iova=%llx physical=%llx translated=%llx valid=1\n",
        p->request_id,p->index,sys_dma.address,(NvU64)host_phys,(NvU64)translated);
    for(i=0;i<PAGE_SIZE/sizeof(*cpu);++i) WRITE_ONCE(cpu[i],0x6975c23aU^i^(p->index<<8));
    clflush_cache_range(cpu,PAGE_SIZE);wmb();
    phase="reads";
    for(mode=1;mode<=2;++mode) {
        for(seq=(mode-1)*3;seq<mode*3;++seq) {
            bool is_peer=seq%3==1;
            status=cask_iova_one(gpu,local_vid,readback_va,readback,is_peer?iova:sys_dma.address,
                is_peer?expected:(0x6975c23aU^(p->index<<8)),mode,seq,p,&pending);
            if(status!=NV_OK) goto done;
        }
    }
    after=ioread32(mmio);
    for(i=0;i<PAGE_SIZE/sizeof(*cpu);++i) source_changed+=READ_ONCE(cpu[i])!=(0x6975c23aU^i^(p->index<<8));
    pr_info("CASKIOVA request=%llu index=%u stage=source_after cpu_after=%08x source_stable=%u host_source_changed=%u\n",
        p->request_id,p->index,after,after==expected,source_changed);
    if(after!=expected || source_changed) {status=NV_ERR_INVALID_STATE;goto done;}
    p->result_flags|=CASK_IOVA_COMPLETED;
done:
    if(pending) {
        cask_iova_fatal=true;__module_get(THIS_MODULE);p->result_flags|=CASK_IOVA_RETAINED;
        cask_iova_held_gpus[0]=gpus[0];cask_iova_held_gpus[1]=gpus[1];
        cask_iova_held_sys=sys;cask_iova_held_vid=vid;cask_iova_held_dma=iova;
        pr_err("CASKIOVA request=%llu stage=retained pending=1 all_dma_buffers_and_gpus_retained_until_reboot=1\n",p->request_id);
    }
    else {
        uvm_mem_free(vid);uvm_mem_free(sys);
        if(mapped) dma_unmap_resource(dev,iova,PAGE_SIZE,DMA_TO_DEVICE,0);
    }
    if(mmio) pci_iounmap(peer,mmio);
    pr_info("CASKIOVA request=%llu index=%u stage=return operation=%u status=%x flags=%x host_mask=%x peer_mask=%x completed_mask=%x pending=%u dma_unmapped=%u last_phase=%s\n",
        p->request_id,p->index,p->operation,status,p->result_flags,p->host_pass_mask,p->peer_pass_mask,
        p->completed_mask,pending,mapped&&!pending,phase);
    uvm_va_space_up_read_rm(space);
    if(!pending) {uvm_gpu_release(gpus[1]);uvm_gpu_release(gpus[0]);}
unlock:
    mutex_unlock(&cask_iova_lock);
    return status;
}
