/* Read-only remote BAR0 comparison. The sole MMIO offset is NV_PMC_BOOT_0=0,
 * documented R--4R in NVIDIA swref/published/nv_ref.h and used for presence
 * checks in gpuVerifyExistence_IMPL. No remote register is ever written.
 */
#include <linux/io.h>
static bool uvm_cask_bar0_read_control;
module_param(uvm_cask_bar0_read_control, bool, 0400);
MODULE_PARM_DESC(uvm_cask_bar0_read_control, "CaskLogic read-only remote BAR0 BOOT_0 control; default off");

static void cask_bar0_pci(uvm_gpu_t *gpu, NvU64 request, unsigned int mode, const char *phase)
{
    u16 value = 0;
    int rc = pci_read_config_word(gpu->parent->pci_dev, PCI_STATUS, &value);
    pr_info("CASKBAR0 request=%llu stage=pci executor=%s mode=%u phase=%s pci_status=%04x read_rc=%d\n",
            request, cask_phys_bdf(gpu), mode, phase, value, rc);
}

static NV_STATUS cask_bar0_read_control(uvm_gpu_t *gpu, uvm_gpu_t *remote,
                                        unsigned int index, NvU64 request,
                                        uvm_gpu_address_t local_vid,
                                        uvm_gpu_address_t readback_virtual,
                                        NvU32 *readback, bool *pending)
{
    struct pci_dev *target = remote->parent->pci_dev;
    resource_size_t start = pci_resource_start(target, 0);
    resource_size_t length = pci_resource_len(target, 0);
    unsigned long flags = pci_resource_flags(target, 0);
    void __iomem *mapped;
    uvm_push_t storage, *push = &storage;
    NvU32 expected, after, sentinel, actual, launch = cask_phys_launch(gpu);
    unsigned int mode, i, mismatches, guard_changed;
    NV_STATUS status = NV_ERR_INVALID_ADDRESS;
    *pending = false;
    if (!start || length < 4 || !(flags & IORESOURCE_MEM) || (flags & IORESOURCE_PREFETCH) ||
        gpu->parent->dma_addressable_limit < 3 || start > gpu->parent->dma_addressable_limit - 3)
        return status;
    mapped = pci_iomap_range(target, 0, 0, 4);
    if (!mapped)
        return NV_ERR_NO_MEMORY;
    expected = ioread32(mapped);
    pr_info("CASKBAR0 request=%llu stage=cpu_reference executor=%s index=%u remote=%s bar=0 offset=0 base=%llx length=%llx resource_flags=%lx expected=%08x register=NV_PMC_BOOT_0 read_only=1\n",
            request, cask_phys_bdf(gpu), index, cask_phys_bdf(remote),
            (NvU64)start, (NvU64)length, flags, expected);
    if (!expected || expected == 0xffffffffU) {
        status = NV_ERR_GPU_IS_LOST;
        goto done;
    }
    sentinel = ~expected;
    for (mode = 1; mode <= 2; ++mode) {
        cask_bar0_pci(gpu, request, mode, "before");
        status = cask_host_begin(gpu, remote, push, request, pending);
        if (status != NV_OK)
            goto done;
        gpu->parent->ce_hal->memset_4(push, local_vid, sentinel, PAGE_SIZE);
        gpu->parent->ce_hal->memcopy(push, readback_virtual, local_vid, PAGE_SIZE);
        status = cask_host_wait(push, pending);
        if (status != NV_OK)
            goto done;
        mismatches = 0;
        for (i = 0; i < PAGE_SIZE / sizeof(*readback); ++i)
            mismatches += READ_ONCE(readback[i]) != sentinel;
        pr_info("CASKBAR0 request=%llu stage=baseline executor=%s index=%u mode=%u checked_words=%lu expected=%08x actual=%08x mismatches=%u valid=%u\n",
                request, cask_phys_bdf(gpu), index, mode, PAGE_SIZE / sizeof(*readback),
                sentinel, READ_ONCE(readback[0]), mismatches, !mismatches);
        if (mismatches) {
            status = NV_ERR_INVALID_STATE;
            goto done;
        }
        status = cask_host_begin(gpu, remote, push, request, pending);
        if (status != NV_OK)
            goto done;
        pr_info("CASKBAR0 request=%llu stage=methods executor=%s index=%u remote=%s mode=%u source_phys=%llx destination_phys=%llx bytes=4 class=c7b5 launch=%x p2p=1 privileged=1 register_offset=0 read_only=1\n",
                request, cask_phys_bdf(gpu), index, cask_phys_bdf(remote), mode,
                (NvU64)start, local_vid.address, launch);
        cask_phys_emit(push, gpu, start, local_vid.address, mode, 0, launch);
        status = cask_host_wait(push, pending);
        if (status != NV_OK)
            goto done;
        cask_bar0_pci(gpu, request, mode, "after_raw");
        status = cask_host_begin(gpu, remote, push, request, pending);
        if (status != NV_OK)
            goto done;
        gpu->parent->ce_hal->memcopy(push, readback_virtual, local_vid, PAGE_SIZE);
        status = cask_host_wait(push, pending);
        if (status != NV_OK)
            goto done;
        actual = READ_ONCE(readback[0]);
        guard_changed = 0;
        for (i = 1; i < PAGE_SIZE / sizeof(*readback); ++i)
            guard_changed += READ_ONCE(readback[i]) != sentinel;
        after = ioread32(mapped);
        pr_info("CASKBAR0 request=%llu stage=result executor=%s index=%u remote=%s mode=%u bytes=4 checked_words=%lu expected=%08x actual=%08x sentinel=%08x match=%u guard_changed=%u cpu_after=%08x source_stable=%u\n",
                request, cask_phys_bdf(gpu), index, cask_phys_bdf(remote), mode,
                PAGE_SIZE / sizeof(*readback), expected, actual, sentinel,
                actual == expected, guard_changed, after, after == expected);
        cask_bar0_pci(gpu, request, mode, "after_readback");
        if (guard_changed || after != expected) {
            status = NV_ERR_INVALID_STATE;
            goto done;
        }
        /* A mismatching read is an experimental data result, not a reason to
         * skip the other direction. Completion and memory guards are required. */
    }
    status = NV_OK;
done:
    pci_iounmap(target, mapped);
    pr_info("CASKBAR0 request=%llu stage=return executor=%s index=%u status=%x pending=%u\n",
            request, cask_phys_bdf(gpu), index, status, *pending);
    return status;
}
