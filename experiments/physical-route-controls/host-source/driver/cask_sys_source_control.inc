/* Four bounded positive controls for the raw SYS-source CE method sequence.
 * All addresses are resolved from new UVM-owned allocations. No user physical
 * address, existing user buffer, firmware or PCI configuration is written.
 * Included by cask_phys_ce.inc after the shared C7B5 emitter definitions.
 */
#include "uvm_mem.h"
#include <asm/cacheflush.h>

static bool uvm_cask_sys_source_control;
module_param(uvm_cask_sys_source_control, bool, 0400);
MODULE_PARM_DESC(uvm_cask_sys_source_control, "CaskLogic private host-source positive controls; default off");
static bool cask_host_done[2];
static uvm_mem_t *cask_host_held_sys, *cask_host_held_vid;

static NV_STATUS cask_host_wait(uvm_push_t *push, bool *pending)
{
    NV_STATUS status;
    *pending = true;
    uvm_push_end(push);
    status = uvm_push_wait(push);
    if (status == NV_OK)
        *pending = false;
    return status;
}

static void cask_host_pci(uvm_gpu_t *gpu, NvU64 request, unsigned int mode, const char *phase)
{
    u16 value = 0;
    int rc = pci_read_config_word(gpu->parent->pci_dev, PCI_STATUS, &value);
    pr_info("CASKHOST request=%llu stage=pci executor=%s mode=%u phase=%s pci_status=%04x read_rc=%d\n",
            request, cask_phys_bdf(gpu), mode, phase, value, rc);
}

static NV_STATUS cask_host_begin(uvm_gpu_t *gpu, uvm_gpu_t *remote, uvm_push_t *push,
                                 NvU64 request, bool *pending)
{
    NV_STATUS status = uvm_push_begin_gpu_to_gpu(gpu->channel_manager, remote, push,
                                                "CaskLogic SYS source control %llu", request);
    if (status != NV_OK)
        return status;
    if (!uvm_channel_is_p2p(push->channel) || !uvm_channel_is_privileged(push->channel) ||
        uvm_channel_is_proxy(push->channel) || !uvm_channel_is_ce(push->channel) ||
        uvm_channel_get_gpu(push->channel) != gpu) {
        status = cask_host_wait(push, pending);
        return status == NV_OK ? NV_ERR_NOT_SUPPORTED : status;
    }
    return NV_OK;
}

static NV_STATUS cask_host_source_control(uvm_gpu_t *gpu, uvm_gpu_t *remote,
                                           unsigned int index, NvU64 request, bool *pending)
{
    uvm_mem_t *sys = NULL, *vid = NULL;
    uvm_gpu_address_t sys_virtual, readback_virtual, sys_physical, vid_physical;
    uvm_push_t storage, *push = &storage;
    NvU32 *cpu, *readback;
    NvU32 expected, sentinel, launch;
    unsigned int mode, i, mismatches, source_changed;
    NV_STATUS status;
    const char *phase = "allocate_host";
    *pending = false;
    if (index > 1 || gpu->parent->rm_info.ceClass != AMPERE_DMA_COPY_B ||
        g_uvm_global.conf_computing_enabled || gpu->parent->dma_addressable_start != 0)
        return NV_ERR_NOT_SUPPORTED;
    status = uvm_mem_alloc_sysmem_and_map_cpu_kernel(2 * PAGE_SIZE, current->mm, &sys);
    if (status != NV_OK)
        goto done;
    phase = "allocate_vidmem";
    status = uvm_mem_alloc_vidmem(PAGE_SIZE, gpu, &vid);
    if (status != NV_OK)
        goto done;
    phase = "map_host";
    status = uvm_mem_map_gpu_kernel(sys, gpu);
    if (status != NV_OK)
        goto done;
    phase = "map_vidmem";
    status = uvm_mem_map_gpu_kernel(vid, gpu);
    if (status != NV_OK)
        goto done;
    cpu = uvm_mem_get_cpu_addr_kernel(sys);
    readback = (NvU32 *)((char *)cpu + PAGE_SIZE);
    sys_virtual = uvm_mem_gpu_address_virtual_kernel(sys, gpu);
    readback_virtual = sys_virtual;
    readback_virtual.address += PAGE_SIZE;
    sys_physical = uvm_mem_gpu_address_physical(sys, gpu, 0, 4);
    vid_physical = uvm_mem_gpu_address_physical(vid, gpu, 0, PAGE_SIZE);
    if (sys_physical.is_virtual || vid_physical.is_virtual ||
        sys_physical.aperture != UVM_APERTURE_SYS || vid_physical.aperture != UVM_APERTURE_VID ||
        !sys_physical.address || !vid_physical.address ||
        (sys_physical.address & 3) || (vid_physical.address & 3) ||
        gpu->parent->dma_addressable_limit < 3 ||
        sys_physical.address > gpu->parent->dma_addressable_limit - 3 ||
        gpu->mem_info.max_allocatable_address < PAGE_SIZE - 1 ||
        vid_physical.address > gpu->mem_info.max_allocatable_address - (PAGE_SIZE - 1)) {
        status = NV_ERR_INVALID_ADDRESS;
        goto done;
    }
    launch = cask_phys_launch(gpu);
    for (mode = 1; mode <= 2; ++mode) {
        expected = 0x6975c23aU ^ ((index + 1) * 0x11a33799U) ^ (mode * 0x9e3779b9U);
        sentinel = ~expected;
        for (i = 0; i < PAGE_SIZE / sizeof(*cpu); ++i) {
            WRITE_ONCE(cpu[i], i ? (0x6c713550U ^ i) : expected);
            WRITE_ONCE(readback[i], 0);
        }
        /* Materialize the private source in DRAM before either SYS mode.
         * This prevents dirty CPU cache lines from confounding the raw read. */
        clflush_cache_range(cpu, PAGE_SIZE);
        wmb();
        cask_host_pci(gpu, request, mode, "before");
        phase = "baseline_begin";
        status = cask_host_begin(gpu, remote, push, request, pending);
        if (status != NV_OK)
            goto done;
        gpu->parent->ce_hal->memset_4(push, vid_physical, sentinel, PAGE_SIZE);
        gpu->parent->ce_hal->memcopy(push, readback_virtual, vid_physical, PAGE_SIZE);
        phase = "baseline_wait";
        status = cask_host_wait(push, pending);
        if (status != NV_OK)
            goto done;
        mismatches = 0;
        for (i = 0; i < PAGE_SIZE / sizeof(*cpu); ++i)
            mismatches += READ_ONCE(readback[i]) != sentinel;
        pr_info("CASKHOST request=%llu stage=baseline executor=%s index=%u mode=%u checked_words=%lu expected=%08x actual=%08x mismatches=%u valid=%u\n",
                request, cask_phys_bdf(gpu), index, mode, PAGE_SIZE / sizeof(*cpu),
                sentinel, READ_ONCE(readback[0]), mismatches, !mismatches);
        if (mismatches) {
            status = NV_ERR_INVALID_STATE;
            goto done;
        }
        cask_host_pci(gpu, request, mode, "after_baseline");
        phase = "raw_begin";
        status = cask_host_begin(gpu, remote, push, request, pending);
        if (status != NV_OK)
            goto done;
        pr_info("CASKHOST request=%llu stage=methods executor=%s index=%u mode=%u source_phys=%llx destination_phys=%llx bytes=4 class=c7b5 launch=%x p2p=1 privileged=1 no_virtual_fallback=1\n",
                request, cask_phys_bdf(gpu), index, mode, sys_physical.address, vid_physical.address, launch);
        cask_phys_emit(push, gpu, sys_physical.address, vid_physical.address, mode, 0, launch);
        phase = "raw_wait";
        status = cask_host_wait(push, pending);
        if (status != NV_OK)
            goto done;
        cask_host_pci(gpu, request, mode, "after_raw");
        phase = "readback_begin";
        status = cask_host_begin(gpu, remote, push, request, pending);
        if (status != NV_OK)
            goto done;
        gpu->parent->ce_hal->memcopy(push, readback_virtual, vid_physical, PAGE_SIZE);
        phase = "readback_wait";
        status = cask_host_wait(push, pending);
        if (status != NV_OK)
            goto done;
        mismatches = source_changed = 0;
        for (i = 0; i < PAGE_SIZE / sizeof(*cpu); ++i) {
            mismatches += READ_ONCE(readback[i]) != (i ? sentinel : expected);
            source_changed += READ_ONCE(cpu[i]) != (i ? (0x6c713550U ^ i) : expected);
        }
        pr_info("CASKHOST request=%llu stage=result executor=%s index=%u mode=%u bytes=4 checked_words=%lu expected=%08x actual=%08x sentinel=%08x mismatches=%u source_changed=%u valid=%u\n",
                request, cask_phys_bdf(gpu), index, mode, PAGE_SIZE / sizeof(*cpu), expected,
                READ_ONCE(readback[0]), sentinel, mismatches, source_changed, !mismatches && !source_changed);
        cask_host_pci(gpu, request, mode, "after_readback");
        if (mismatches || source_changed) {
            status = NV_ERR_INVALID_STATE;
            goto done;
        }
    }
    status = NV_OK;
done:
    pr_info("CASKHOST request=%llu stage=return executor=%s index=%u status=%x pending=%u last_phase=%s\n",
            request, cask_phys_bdf(gpu), index, status, *pending, phase);
    if (*pending) {
        cask_host_held_sys = sys;
        cask_host_held_vid = vid;
        /* Caller retains its three map handles, peer pair and module reference;
         * the existing userspace client parks until the independent watchdog. */
        pr_err("CASKHOST request=%llu completion_unconfirmed private_buffers_retained_until_reboot=1\n", request);
    }
    else {
        uvm_mem_free(vid);
        uvm_mem_free(sys);
    }
    return status;
}
