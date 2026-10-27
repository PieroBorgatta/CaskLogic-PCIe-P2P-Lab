/* Native, quiescent research only. Temporarily alias ONE private VRAM page
 * through documented BAR0_WINDOW/PRAMIN; restore before further RM calls.
 * GPU->GPU data uses raw CE, never a host-memory relay. CPU initializes and
 * verifies only. Not a production transport: no global RM/GSP window lock.
 * Firmware and VM data disks are untouched. Exact native identities and the
 * outer diagnostic serialization/retained GPU+peer references are mandatory.
 */
static bool uvm_cask_pramin_push_control;
module_param(uvm_cask_pramin_push_control, bool, 0400);
MODULE_PARM_DESC(uvm_cask_pramin_push_control, "Native private-page BAR0 PRAMIN PUSH experiment; default off");
static uvm_mem_t *cask_pramin_held_target;

static NvU32 cask_pramin_pattern(unsigned int index, unsigned int mode, unsigned int word, bool source)
{
    return (source ? 0x416ba372U : 0xa73295c1U) ^ ((index + 1) * 0x11889933U) ^
           (mode * 0x517cc1b7U) ^ (word * 0x9e3779b9U);
}

static NV_STATUS cask_pramin_copy(uvm_gpu_t *gpu, uvm_gpu_t *remote,
                                 uvm_gpu_address_t dst, uvm_gpu_address_t src,
                                 NvU64 request, bool *pending)
{
    uvm_push_t push;
    NV_STATUS status = cask_host_begin(gpu, remote, &push, request, pending);
    if (status != NV_OK)
        return status;
    gpu->parent->ce_hal->memcopy(&push, dst, src, PAGE_SIZE);
    return cask_host_wait(&push, pending);
}

static void cask_pramin_pci(uvm_gpu_t *gpu, NvU64 request, unsigned int mode, const char *phase)
{
    u16 value = 0;
    int rc = pci_read_config_word(gpu->parent->pci_dev, PCI_STATUS, &value);
    pr_info("CASKPRAMIN request=%llu stage=pci executor=%s mode=%u phase=%s pci_status=%04x read_rc=%d\n",
            request, cask_phys_bdf(gpu), mode, phase, value, rc);
}

static NV_STATUS cask_pramin_push_control(uvm_gpu_t *gpu, uvm_gpu_t *remote,
                                         unsigned int index, NvU64 request,
                                         uvm_mem_t *sys, uvm_gpu_address_t source_vid,
                                         bool *pending)
{
    struct pci_dev *pci = remote->parent->pci_dev;
    resource_size_t base = pci_resource_start(pci, 0), length = pci_resource_len(pci, 0);
    unsigned long flags = pci_resource_flags(pci, 0);
    uvm_mem_t *target = NULL;
    uvm_gpu_address_t target_vid, src_cpu, dst_cpu, src_readback, dst_readback;
    uvm_push_t push;
    void __iomem *bar = NULL;
    NvU32 *cpu = uvm_mem_get_cpu_addr_kernel(sys), *readback = (NvU32 *)((char *)cpu + PAGE_SIZE);
    NvU32 old_window = 0, new_window = 0, observed, expected, sentinel, alias_actual = 0, actual = 0;
    NvU32 launch = cask_phys_launch(gpu);
    NvU64 offset = 0, destination = 0;
    unsigned int mode, i, source_changed, guard_changed, mismatch, alias_guards;
    bool window_active = false;
    NV_STATUS status = NV_ERR_INVALID_ADDRESS;
    const char *phase = "resource";
    *pending = false;
    if (PAGE_SIZE != 4096 || !base || length < 0x800000 || !(flags & IORESOURCE_MEM) ||
        (flags & IORESOURCE_PREFETCH) || gpu->parent->dma_addressable_limit < 0x7fffff ||
        base > gpu->parent->dma_addressable_limit - 0x7fffff)
        goto done;
    phase = "allocate_target";
    status = uvm_mem_alloc_vidmem(PAGE_SIZE, remote, &target);
    if (status != NV_OK)
        goto done;
    status = uvm_mem_map_gpu_kernel(target, remote);
    if (status != NV_OK)
        goto done;
    status = uvm_mem_map_gpu_kernel(sys, remote);
    if (status != NV_OK)
        goto done;
    target_vid = uvm_mem_gpu_address_physical(target, remote, 0, PAGE_SIZE);
    if (target_vid.is_virtual || target_vid.aperture != UVM_APERTURE_VID || !target_vid.address ||
        (target_vid.address & (PAGE_SIZE - 1)) || (target_vid.address >> 16) > 0xffffffULL ||
        remote->mem_info.max_allocatable_address < PAGE_SIZE - 1 ||
        target_vid.address > remote->mem_info.max_allocatable_address - (PAGE_SIZE - 1)) {
        status = NV_ERR_INVALID_ADDRESS;
        goto done;
    }
    offset = 0x700000 + (target_vid.address & 0xffff);
    destination = base + offset;
    src_cpu = uvm_mem_gpu_address_virtual_kernel(sys, gpu);
    dst_cpu = uvm_mem_gpu_address_virtual_kernel(sys, remote);
    src_readback = src_cpu;
    src_readback.address += PAGE_SIZE;
    dst_readback = dst_cpu;
    dst_readback.address += PAGE_SIZE;
    bar = pci_iomap_range(pci, 0, 0, 0x800000);
    if (!bar) {
        status = NV_ERR_NO_MEMORY;
        goto done;
    }
    pr_info("CASKPRAMIN request=%llu stage=reference executor=%s index=%u remote=%s bar=0 base=%llx length=%llx resource_flags=%lx source_vid=%llx target_vid=%llx alias_offset=%llx alias_phys=%llx bytes=4 window_register=1700 private_target=1\n",
            request, cask_phys_bdf(gpu), index, cask_phys_bdf(remote), (NvU64)base,
            (NvU64)length, flags, source_vid.address, target_vid.address, offset, destination);
    for (mode = 1; mode <= 2; ++mode) {
        expected = cask_pramin_pattern(index, mode, 0, true);
        sentinel = cask_pramin_pattern(index, mode, 0, false);
        phase = "initialize_source";
        for (i = 0; i < PAGE_SIZE / sizeof(*cpu); ++i)
            WRITE_ONCE(cpu[i], cask_pramin_pattern(index, mode, i, true));
        clflush_cache_range(cpu, PAGE_SIZE);
        wmb();
        status = cask_pramin_copy(gpu, remote, source_vid, src_cpu, request, pending);
        if (status != NV_OK) goto done;
        status = cask_pramin_copy(gpu, remote, src_readback, source_vid, request, pending);
        if (status != NV_OK) goto done;
        mismatch = 0;
        for (i = 0; i < PAGE_SIZE / sizeof(*cpu); ++i)
            mismatch += READ_ONCE(readback[i]) != cask_pramin_pattern(index, mode, i, true);
        if (mismatch) { status = NV_ERR_INVALID_STATE; goto done; }
        phase = "initialize_target";
        for (i = 0; i < PAGE_SIZE / sizeof(*cpu); ++i)
            WRITE_ONCE(cpu[i], cask_pramin_pattern(index, mode, i, false));
        clflush_cache_range(cpu, PAGE_SIZE);
        wmb();
        status = cask_pramin_copy(remote, gpu, target_vid, dst_cpu, request, pending);
        if (status != NV_OK) goto done;
        status = cask_pramin_copy(remote, gpu, dst_readback, target_vid, request, pending);
        if (status != NV_OK) goto done;
        mismatch = 0;
        for (i = 0; i < PAGE_SIZE / sizeof(*cpu); ++i)
            mismatch += READ_ONCE(readback[i]) != cask_pramin_pattern(index, mode, i, false);
        pr_info("CASKPRAMIN request=%llu stage=baseline executor=%s index=%u mode=%u checked_words=1024 source_mismatches=0 target_mismatches=%u expected=%08x sentinel=%08x valid=%u\n",
                request, cask_phys_bdf(gpu), index, mode, mismatch, expected, sentinel, !mismatch);
        if (mismatch) { status = NV_ERR_INVALID_STATE; goto done; }
        /* Prepare the channel BEFORE changing BAR0_WINDOW. No RM allocation or
         * mappings may occur while the window is active. */
        phase = "begin_raw";
        status = cask_host_begin(gpu, remote, &push, request, pending);
        if (status != NV_OK) goto done;
        old_window = ioread32(bar + 0x1700);
        if (old_window == 0xffffffffU) {
            status = cask_host_wait(&push, pending);
            if (status == NV_OK) status = NV_ERR_GPU_IS_LOST;
            goto done;
        }
        new_window = (old_window & ~0x03ffffffU) | (NvU32)(target_vid.address >> 16);
        iowrite32(new_window, bar + 0x1700);
        window_active = true;
        observed = ioread32(bar + 0x1700);
        mismatch = 0;
        if (observed == new_window)
            for (i = 0; i < 16; ++i)
                mismatch += ioread32(bar + offset + i * 4) != cask_pramin_pattern(index, mode, i, false);
        else mismatch = 16;
        pr_info("CASKPRAMIN request=%llu stage=window executor=%s index=%u mode=%u old=%08x programmed=%08x observed=%08x alias_checked_words=16 alias_mismatches=%u\n",
                request, cask_phys_bdf(gpu), index, mode, old_window, new_window, observed, mismatch);
        if (mismatch) {
            status = cask_host_wait(&push, pending);
            if (status == NV_OK) status = NV_ERR_INVALID_STATE;
            goto done;
        }
        cask_pramin_pci(gpu, request, mode, "before");
        pr_info("CASKPRAMIN request=%llu stage=methods executor=%s index=%u mode=%u remote=%s source_phys=%llx destination_phys=%llx source_mode=0 destination_mode=%u bytes=4 class=c7b5 launch=%x p2p=1 privileged=1 host_relay=0\n",
                request, cask_phys_bdf(gpu), index, mode, cask_phys_bdf(remote), source_vid.address, destination, mode, launch);
        cask_phys_emit(&push, gpu, source_vid.address, destination, 0, mode, launch);
        phase = "raw_wait";
        status = cask_host_wait(&push, pending);
        if (status != NV_OK) goto done;
        cask_pramin_pci(gpu, request, mode, "after_raw");
        observed = ioread32(bar + 0x1700);
        alias_actual = ioread32(bar + offset);
        alias_guards = 0;
        for (i = 1; i < 16; ++i)
            alias_guards += ioread32(bar + offset + i * 4) != cask_pramin_pattern(index, mode, i, false);
        phase = "restore_window";
        iowrite32(old_window, bar + 0x1700);
        window_active = false;
        if (ioread32(bar + 0x1700) != old_window || observed != new_window) {
            *pending = true; /* Unknown global alias state: park until reboot. */
            status = NV_ERR_INVALID_STATE;
            goto done;
        }
        pr_info("CASKPRAMIN request=%llu stage=restored executor=%s index=%u mode=%u old=%08x observed_during=%08x restored=%08x alias_actual=%08x alias_guard_changed=%u\n",
                request, cask_phys_bdf(gpu), index, mode, old_window, observed, old_window, alias_actual, alias_guards);
        phase = "readback_target";
        status = cask_pramin_copy(remote, gpu, dst_readback, target_vid, request, pending);
        if (status != NV_OK) goto done;
        actual = READ_ONCE(readback[0]);
        guard_changed = 0;
        for (i = 1; i < PAGE_SIZE / sizeof(*cpu); ++i)
            guard_changed += READ_ONCE(readback[i]) != cask_pramin_pattern(index, mode, i, false);
        phase = "readback_source";
        status = cask_pramin_copy(gpu, remote, src_readback, source_vid, request, pending);
        if (status != NV_OK) goto done;
        source_changed = 0;
        for (i = 0; i < PAGE_SIZE / sizeof(*cpu); ++i)
            source_changed += READ_ONCE(readback[i]) != cask_pramin_pattern(index, mode, i, true);
        pr_info("CASKPRAMIN request=%llu stage=result executor=%s index=%u mode=%u remote=%s bytes=4 checked_words=1024 expected=%08x sentinel=%08x actual=%08x alias_actual=%08x match=%u alias_match=%u guard_changed=%u alias_guard_changed=%u source_changed=%u\n",
                request, cask_phys_bdf(gpu), index, mode, cask_phys_bdf(remote), expected, sentinel, actual, alias_actual,
                actual == expected, alias_actual == expected, guard_changed, alias_guards, source_changed);
        cask_pramin_pci(gpu, request, mode, "after_readback");
        if (guard_changed || alias_guards || source_changed || actual != alias_actual) {
            status = NV_ERR_INVALID_STATE;
            goto done;
        }
    }
    status = NV_OK;
done:
    if (window_active && !*pending) {
        iowrite32(old_window, bar + 0x1700);
        if (ioread32(bar + 0x1700) != old_window) *pending = true;
    }
    pr_info("CASKPRAMIN request=%llu stage=return executor=%s index=%u status=%x pending=%u last_phase=%s\n",
            request, cask_phys_bdf(gpu), index, status, *pending, phase);
    if (*pending) {
        cask_pramin_held_target = target;
        pr_err("CASKPRAMIN completion_unconfirmed private_target_and_outer_buffers_retained_until_reboot=1\n");
    }
    else uvm_mem_free(target);
    if (bar) pci_iounmap(pci, bar);
    return status;
}
