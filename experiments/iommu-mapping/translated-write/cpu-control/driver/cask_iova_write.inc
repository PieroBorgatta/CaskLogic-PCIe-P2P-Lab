/* Isolated native diagnostic for four-byte writes from private local VIDMEM
 * to a private peer VIDMEM page exposed by an RM-managed CPU/BAR1 mapping.
 *
 * The BAR1 bus address is derived from the present 4 KiB kernel PTE of that
 * live mapping, then checked against the exact remote PCI BAR resource. It is
 * mapped into the requester's strict DMA domain with DMA_FROM_DEVICE. No BAR
 * offset, RM handle, physical address or user buffer is accepted as input.
 * Ordinary CUDA peer access is never enabled. Owner-GPU readback is primary;
 * a CPU BAR1 read is logged only after owner readback as a secondary control.
 * After all peer results, one CPU MMIO write to the same private target is
 * flushed by an MMIO read and verified by the owner GPU. It is a topology
 * control only and never relays a peer payload.
 */
#include "uvm_mem.h"
#include "uvm_rm_mem.h"
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
#include <asm/cpufeature.h>
#include <asm/pgtable.h>
#include <asm/processor.h>

static bool uvm_cask_iova_write;
module_param(uvm_cask_iova_write, bool, 0400);
MODULE_PARM_DESC(uvm_cask_iova_write, "Native private peer BAR1 writes through translated DMA IOVA; default off");

static DEFINE_MUTEX(cask_iova_write_lock);
static bool cask_iova_write_used[2], cask_iova_write_fatal;
/* On uncertain completion every object that can back an in-flight access is
 * retained until reboot, including the RM BAR1 mapping and DMA mapping. */
static uvm_gpu_t *cask_iova_write_held_gpus[2];
static uvm_mem_t *cask_iova_write_held_sys, *cask_iova_write_held_source;
static uvm_rm_mem_t *cask_iova_write_held_target;
static dma_addr_t cask_iova_write_held_dma;

static bool cask_iova_write_gpu(uvm_gpu_t *gpu, unsigned int index, const NvU8 *uuid)
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

static NV_STATUS cask_iova_write_wait(uvm_push_t *push, bool *pending)
{
    NV_STATUS status;

    *pending = true;
    uvm_push_end(push);
    status = uvm_push_wait(push);
    if (status == NV_OK)
        *pending = false;
    return status;
}

static NV_STATUS cask_iova_write_begin(uvm_gpu_t *gpu, uvm_push_t *push, bool *pending)
{
    NV_STATUS status = uvm_push_begin(gpu->channel_manager,
                                      UVM_CHANNEL_TYPE_CPU_TO_GPU,
                                      push,
                                      "CaskLogic translated private BAR1 write");
    if (status != NV_OK)
        return status;

    if (!uvm_channel_is_privileged(push->channel) ||
        uvm_channel_is_proxy(push->channel) ||
        !uvm_channel_is_ce(push->channel) ||
        uvm_channel_is_p2p(push->channel) ||
        uvm_channel_get_gpu(push->channel) != gpu) {
        status = cask_iova_write_wait(push, pending);
        return status == NV_OK ? NV_ERR_NOT_SUPPORTED : status;
    }

    return NV_OK;
}

static NvU32 cask_iova_write_launch(uvm_gpu_t *gpu)
{
    return HWCONST(C7B5,LAUNCH_DMA,SRC_MEMORY_LAYOUT,PITCH) |
           HWCONST(C7B5,LAUNCH_DMA,DST_MEMORY_LAYOUT,PITCH) |
           HWCONST(C7B5,LAUNCH_DMA,MULTI_LINE_ENABLE,FALSE) |
           HWCONST(C7B5,LAUNCH_DMA,REMAP_ENABLE,FALSE) |
           HWCONST(C7B5,LAUNCH_DMA,FLUSH_ENABLE,TRUE) |
           HWCONST(C7B5,LAUNCH_DMA,FLUSH_TYPE,SYS) |
           HWCONST(C7B5,LAUNCH_DMA,SRC_TYPE,PHYSICAL) |
           HWCONST(C7B5,LAUNCH_DMA,DST_TYPE,PHYSICAL) |
           HWCONST(C7B5,LAUNCH_DMA,DATA_TRANSFER_TYPE,NON_PIPELINED) |
           gpu->parent->ce_hal->plc_mode();
}

static void cask_iova_write_emit(uvm_push_t *push,
                                 uvm_gpu_t *gpu,
                                 NvU64 source,
                                 NvU64 destination,
                                 NvU32 mode)
{
    NvU32 source_mode = HWCONST(C7B5,SET_SRC_PHYS_MODE,TARGET,LOCAL_FB);

    BUILD_BUG_ON(NVC6B5_SET_SRC_PHYS_MODE != NVC7B5_SET_SRC_PHYS_MODE);
    BUILD_BUG_ON(NVC6B5_SET_DST_PHYS_MODE != NVC7B5_SET_DST_PHYS_MODE);
    BUILD_BUG_ON(NVC6B5_LINE_LENGTH_IN != NVC7B5_LINE_LENGTH_IN);
    BUILD_BUG_ON(NVC6B5_LAUNCH_DMA != NVC7B5_LAUNCH_DMA);
    NV_PUSH_2U(C6B5, SET_SRC_PHYS_MODE, source_mode,
                     SET_DST_PHYS_MODE, mode);
    gpu->parent->ce_hal->offset_in_out(push, source, destination);
    NV_PUSH_1U(C6B5, LINE_LENGTH_IN, 4);
    NV_PUSH_1U(C6B5, LAUNCH_DMA, cask_iova_write_launch(gpu));
}

static NV_STATUS cask_iova_write_fill_read(uvm_gpu_t *gpu,
                                           uvm_gpu_address_t object,
                                           uvm_gpu_address_t readback,
                                           NvU32 pattern,
                                           bool *pending)
{
    uvm_push_t push;
    NV_STATUS status = cask_iova_write_begin(gpu, &push, pending);

    if (status != NV_OK)
        return status;
    gpu->parent->ce_hal->memset_4(&push, object, pattern, PAGE_SIZE);
    gpu->parent->ce_hal->memcopy(&push, readback, object, PAGE_SIZE);
    return cask_iova_write_wait(&push, pending);
}

static NV_STATUS cask_iova_write_read(uvm_gpu_t *gpu,
                                      uvm_gpu_address_t object,
                                      uvm_gpu_address_t readback,
                                      bool *pending)
{
    uvm_push_t push;
    NV_STATUS status = cask_iova_write_begin(gpu, &push, pending);

    if (status != NV_OK)
        return status;
    gpu->parent->ce_hal->memcopy(&push, readback, object, PAGE_SIZE);
    return cask_iova_write_wait(&push, pending);
}

static unsigned int cask_iova_write_mismatches(const NvU32 *buffer, NvU32 expected, unsigned int first)
{
    unsigned int i, mismatches = 0;

    for (i = first; i < PAGE_SIZE / sizeof(*buffer); ++i)
        mismatches += READ_ONCE(buffer[i]) != expected;
    return mismatches;
}

static NvU32 cask_iova_write_source_pattern(unsigned int index, unsigned int mode)
{
    return 0x35a761c9U ^ ((index + 1) * 0x1193a7d5U) ^ (mode * 0x6d2b79f1U);
}

static NvU32 cask_iova_write_target_sentinel(unsigned int index, unsigned int mode)
{
    return 0xc39e14a7U ^ ((index + 1) * 0x4b17d263U) ^ (mode * 0x92745b31U);
}

static NvU32 cask_iova_write_host_sentinel(unsigned int index, unsigned int mode, unsigned int seq)
{
    return 0x8e51c3b9U ^ ((index + 1) * 0x71ad0965U) ^
           (mode * 0x2d679f43U) ^ (seq * 0x1337a921U);
}

static NvU32 cask_iova_write_cpu_pattern(unsigned int index)
{
    return 0x4dd8a621U ^ ((index + 1) * 0x7c4f2935U);
}

static NvU32 cask_iova_write_cpu_sentinel(unsigned int index)
{
    return 0x63b71dc9U ^ ((index + 1) * 0x29e4c583U);
}

/* Resolve only the present 4 KiB PTE created by the live RM CPU mapping.
 * This is x86/kernel-version-specific diagnostic instrumentation, not a
 * portable NVIDIA P2P API. */
static bool cask_iova_write_resolve_bar1(uvm_gpu_t *owner,
                                         void *cpu_va,
                                         resource_size_t *physical_out,
                                         resource_size_t *bar_start_out,
                                         resource_size_t *bar_length_out,
                                         unsigned int *level_out,
                                         int *bar_index_out,
                                         unsigned long *resource_flags_out)
{
    struct pci_dev *pci = owner->parent->pci_dev;
    unsigned long address = (unsigned long)cpu_va;
    unsigned long flags;
    resource_size_t physical, start, length;
    unsigned int level = 0;
    int bar_index;
    pte_t *pte;

    if (!cpu_va || !PAGE_ALIGNED(address))
        return false;
    pte = lookup_address(address, &level);
    if (!pte || level != PG_LEVEL_4K || !pte_present(*pte))
        return false;

    physical = (resource_size_t)PFN_PHYS(pte_pfn(*pte));
    bar_index = uvm_device_p2p_static_bar(owner->parent);
    if (bar_index < 0 || bar_index >= PCI_STD_NUM_BARS)
        return false;
    start = pci_resource_start(pci, bar_index);
    length = pci_resource_len(pci, bar_index);
    flags = pci_resource_flags(pci, bar_index);

    if (!start || length < PAGE_SIZE || start > (resource_size_t)-1 - length ||
        !(flags & IORESOURCE_MEM) || !(flags & IORESOURCE_PREFETCH) ||
        physical < start || physical > start + length - PAGE_SIZE)
        return false;

    *physical_out = physical;
    *bar_start_out = start;
    *bar_length_out = length;
    *level_out = level;
    *bar_index_out = bar_index;
    *resource_flags_out = flags;
    return true;
}

static unsigned int cask_iova_write_alias_mismatches(void *cpu_va,
                                                      NvU32 expected,
                                                      unsigned int words)
{
    unsigned int i, mismatches = 0;

    for (i = 0; i < words; ++i)
        mismatches += ioread32((char __iomem *)cpu_va + i * sizeof(NvU32)) != expected;
    return mismatches;
}

static NV_STATUS cask_iova_write_alias_check(uvm_gpu_t *owner,
                                             unsigned int index,
                                             NvU64 request,
                                             uvm_rm_mem_t *target,
                                             uvm_gpu_address_t target_readback,
                                             NvU32 *readback,
                                             void *cpu_va,
                                             UVM_TEST_CASK_IOVA_WRITE_PARAMS *p,
                                             bool *pending)
{
    uvm_gpu_address_t target_va = uvm_rm_mem_get_gpu_va(target, owner, false);
    NvU32 pattern_a = 0x7ac351e9U ^ ((index + 1) * 0x16579b3dU);
    NvU32 pattern_b = 0x91de2f47U ^ ((index + 1) * 0x4cb78365U);
    NvU32 reset = cask_iova_write_target_sentinel(index, 0);
    NvU32 cpu_a = 0, cpu_b = 0, cpu_reset = 0;
    unsigned int mismatch_a, mismatch_b, mismatch_reset;
    unsigned int cpu_mismatch_a, cpu_mismatch_b, cpu_mismatch_reset;
    NV_STATUS status;

    status = cask_iova_write_fill_read(owner, target_va, target_readback, pattern_a, pending);
    if (status != NV_OK)
        return status;
    mismatch_a = cask_iova_write_mismatches(readback, pattern_a, 0);
    if (!mismatch_a)
        p->alias_pass_mask |= 1U << 0;
    cpu_a = ioread32((void __iomem *)cpu_va);
    cpu_mismatch_a = cask_iova_write_alias_mismatches(cpu_va, pattern_a, 16);
    if (!cpu_mismatch_a)
        p->alias_pass_mask |= 1U << 1;

    status = cask_iova_write_fill_read(owner, target_va, target_readback, pattern_b, pending);
    if (status != NV_OK)
        return status;
    mismatch_b = cask_iova_write_mismatches(readback, pattern_b, 0);
    if (!mismatch_b)
        p->alias_pass_mask |= 1U << 2;
    cpu_b = ioread32((void __iomem *)cpu_va);
    cpu_mismatch_b = cask_iova_write_alias_mismatches(cpu_va, pattern_b, 16);
    if (!cpu_mismatch_b)
        p->alias_pass_mask |= 1U << 3;

    status = cask_iova_write_fill_read(owner, target_va, target_readback, reset, pending);
    if (status != NV_OK)
        return status;
    mismatch_reset = cask_iova_write_mismatches(readback, reset, 0);
    cpu_reset = ioread32((void __iomem *)cpu_va);
    cpu_mismatch_reset = cask_iova_write_alias_mismatches(cpu_va, reset, 16);

    pr_info("CASKIOVAWRITE request=%llu index=%u stage=alias owner=%s private_target=1 rm_cpu_map=1 alias_words=16 owner_a_mismatches=%u cpu_a=%08x cpu_a_mismatches=%u expected_a=%08x owner_b_mismatches=%u cpu_b=%08x cpu_b_mismatches=%u expected_b=%08x owner_reset_mismatches=%u cpu_reset=%08x cpu_reset_mismatches=%u alias_mask=%x\n",
            request,
            index,
            pci_name(owner->parent->pci_dev),
            mismatch_a,
            cpu_a,
            cpu_mismatch_a,
            pattern_a,
            mismatch_b,
            cpu_b,
            cpu_mismatch_b,
            pattern_b,
            mismatch_reset,
            cpu_reset,
            cpu_mismatch_reset,
            p->alias_pass_mask);

    if (mismatch_a || mismatch_b || mismatch_reset ||
        cpu_mismatch_a || cpu_mismatch_b || cpu_mismatch_reset ||
        p->alias_pass_mask != 0xf)
        return NV_ERR_INVALID_STATE;
    p->result_flags |= CASK_IOVA_WRITE_ALIAS_VERIFIED;
    return NV_OK;
}

static NV_STATUS cask_iova_write_source_check(uvm_gpu_t *gpu,
                                              uvm_gpu_address_t source,
                                              uvm_gpu_address_t readback_va,
                                              NvU32 *readback,
                                              NvU32 expected,
                                              unsigned int *changed,
                                              bool *pending)
{
    NV_STATUS status = cask_iova_write_read(gpu, source, readback_va, pending);

    if (status != NV_OK)
        return status;
    *changed = cask_iova_write_mismatches(readback, expected, 0);
    return NV_OK;
}

static NV_STATUS cask_iova_write_one(uvm_gpu_t *gpu,
                                     uvm_gpu_t *owner,
                                     uvm_gpu_address_t source,
                                     uvm_gpu_address_t source_readback_va,
                                     NvU32 *source_readback,
                                     uvm_gpu_address_t target_va,
                                     uvm_gpu_address_t target_readback_va,
                                     NvU32 *target_readback,
                                     NvU32 *host_cpu,
                                     void *target_cpu_va,
                                     NvU64 host_iova,
                                     NvU64 peer_iova,
                                     unsigned int mode,
                                     unsigned int seq,
                                     unsigned int index,
                                     UVM_TEST_CASK_IOVA_WRITE_PARAMS *p,
                                     bool *pending)
{
    const bool peer = seq % 3 == 1;
    NvU32 expected = cask_iova_write_source_pattern(index, mode);
    NvU32 sentinel = peer ? cask_iova_write_target_sentinel(index, mode) :
                            cask_iova_write_host_sentinel(index, mode, seq);
    NvU32 actual, alias_actual = 0;
    unsigned int guard_changed, alias_guard_changed = 0, source_changed;
    uvm_push_t push;
    NV_STATUS status;
    unsigned int i;

    if (peer) {
        status = cask_iova_write_fill_read(owner,
                                           target_va,
                                           target_readback_va,
                                           sentinel,
                                           pending);
        if (status != NV_OK)
            return status;
        if (cask_iova_write_mismatches(target_readback, sentinel, 0))
            return NV_ERR_INVALID_STATE;
    }
    else {
        for (i = 0; i < PAGE_SIZE / sizeof(*host_cpu); ++i)
            WRITE_ONCE(host_cpu[i], sentinel);
        clflush_cache_range(host_cpu, PAGE_SIZE);
        wmb();
    }

    status = cask_iova_write_begin(gpu, &push, pending);
    if (status != NV_OK)
        return status;
    cask_iova_write_emit(&push,
                         gpu,
                         source.address,
                         peer ? peer_iova : host_iova,
                         mode);
    p->result_flags |= CASK_IOVA_WRITE_SUBMITTED;
    status = cask_iova_write_wait(&push, pending);
    if (status != NV_OK)
        return status;

    if (peer) {
        status = cask_iova_write_read(owner, target_va, target_readback_va, pending);
        if (status != NV_OK)
            return status;
        actual = READ_ONCE(target_readback[0]);
        guard_changed = cask_iova_write_mismatches(target_readback, sentinel, 1);

        /* Secondary observation only, deliberately after the owner-GPU
         * readback. It is logged but cannot make the primary result either
         * succeed or fail. */
        alias_actual = ioread32((void __iomem *)target_cpu_va);
        for (i = 1; i < 16; ++i)
            alias_guard_changed += ioread32((char __iomem *)target_cpu_va + i * sizeof(NvU32)) != sentinel;
    }
    else {
        rmb();
        actual = READ_ONCE(host_cpu[0]);
        guard_changed = cask_iova_write_mismatches(host_cpu, sentinel, 1);
    }

    status = cask_iova_write_source_check(gpu,
                                          source,
                                          source_readback_va,
                                          source_readback,
                                          expected,
                                          &source_changed,
                                          pending);
    if (status != NV_OK)
        return status;

    pr_info("CASKIOVAWRITE request=%llu index=%u stage=result seq=%u mode=%u kind=%s destination_iova=%llx bytes=4 expected=%08x actual=%08x sentinel=%08x match=%u guard_changed=%u source_changed=%u owner_gpu_readback=%u alias_actual=%08x alias_match=%u alias_guard_changed=%u class=c7b5 launch=%x p2p_channel=0 privileged=1 host_relay=0\n",
            p->request_id,
            p->index,
            seq,
            mode,
            peer ? "peer_bar1" : "host_ram",
            peer ? peer_iova : host_iova,
            expected,
            actual,
            sentinel,
            actual == expected,
            guard_changed,
            source_changed,
            peer,
            alias_actual,
            peer && alias_actual == expected,
            alias_guard_changed,
            cask_iova_write_launch(gpu));

    p->completed_mask |= 1U << seq;
    if (guard_changed || source_changed)
        return NV_ERR_INVALID_STATE;

    if (peer) {
        if (actual == expected)
            p->peer_pass_mask |= 1U << (mode - 1);
    }
    else {
        if (actual != expected)
            return NV_ERR_INVALID_STATE;
        p->host_pass_mask |= 1U << seq;
    }

    return NV_OK;
}

/* This control deliberately runs only after all peer-write observations. The
 * read following iowrite32 drains the posted CPU MMIO write; mmiowb() alone is
 * not used as a completion primitive. The owner-GPU full-page readback is the
 * primary observation. CPU reads are recorded but cannot make it pass. */
static NV_STATUS cask_iova_write_cpu_control(uvm_gpu_t *gpu,
                                             uvm_gpu_t *owner,
                                             uvm_gpu_address_t source,
                                             uvm_gpu_address_t source_readback_va,
                                             NvU32 *source_readback,
                                             uvm_gpu_address_t target_va,
                                             uvm_gpu_address_t target_readback_va,
                                             NvU32 *target_readback,
                                             void *target_cpu_va,
                                             unsigned int index,
                                             UVM_TEST_CASK_IOVA_WRITE_PARAMS *p,
                                             bool *pending)
{
    NvU32 pattern = cask_iova_write_cpu_pattern(index);
    NvU32 sentinel = cask_iova_write_cpu_sentinel(index);
    NvU32 source_expected = cask_iova_write_source_pattern(index, 2);
    NvU32 owner_actual, cpu_actual, cpu_reset;
    unsigned int guard_changed, source_changed, reset_owner_mismatches;
    unsigned int reset_cpu_mismatches;
    NV_STATUS status;

    if (p->completed_mask != 0x3f)
        return NV_ERR_INVALID_STATE;

    status = cask_iova_write_fill_read(owner,
                                       target_va,
                                       target_readback_va,
                                       sentinel,
                                       pending);
    if (status != NV_OK)
        return status;
    if (cask_iova_write_mismatches(target_readback, sentinel, 0))
        return NV_ERR_INVALID_STATE;

    wmb();
    iowrite32(pattern, (void __iomem *)target_cpu_va);
    cpu_actual = ioread32((void __iomem *)target_cpu_va);

    status = cask_iova_write_read(owner, target_va, target_readback_va, pending);
    if (status != NV_OK)
        return status;
    owner_actual = READ_ONCE(target_readback[0]);
    guard_changed = cask_iova_write_mismatches(target_readback, sentinel, 1);

    status = cask_iova_write_source_check(gpu,
                                          source,
                                          source_readback_va,
                                          source_readback,
                                          source_expected,
                                          &source_changed,
                                          pending);
    if (status != NV_OK)
        return status;

    status = cask_iova_write_fill_read(owner,
                                       target_va,
                                       target_readback_va,
                                       sentinel,
                                       pending);
    if (status != NV_OK)
        return status;
    reset_owner_mismatches = cask_iova_write_mismatches(target_readback, sentinel, 0);
    cpu_reset = ioread32((void __iomem *)target_cpu_va);
    reset_cpu_mismatches = cask_iova_write_alias_mismatches(target_cpu_va, sentinel, 16);

    if (owner_actual == pattern)
        p->cpu_control_mask |= 1U << 0;
    if (cpu_actual == pattern)
        p->cpu_control_mask |= 1U << 1;
    if (!reset_owner_mismatches)
        p->cpu_control_mask |= 1U << 2;
    if (!reset_cpu_mismatches)
        p->cpu_control_mask |= 1U << 3;

    pr_info("CASKIOVAWRITE request=%llu index=%u stage=cpu_write_control executor=%s owner=%s pattern=%08x sentinel=%08x cpu_actual=%08x cpu_match=%u owner_actual=%08x owner_match=%u guard_changed=%u source_changed=%u reset_owner_mismatches=%u cpu_reset=%08x reset_cpu_mismatches=%u cpu_control_mask=%x owner_gpu_readback_primary=1 cpu_observation_secondary=1 ordering=iowrite32_ioread32_flush after_peer_results=1 peer_payload_relay=0 control_only=1\n",
            p->request_id,
            p->index,
            pci_name(gpu->parent->pci_dev),
            pci_name(owner->parent->pci_dev),
            pattern,
            sentinel,
            cpu_actual,
            cpu_actual == pattern,
            owner_actual,
            owner_actual == pattern,
            guard_changed,
            source_changed,
            reset_owner_mismatches,
            cpu_reset,
            reset_cpu_mismatches,
            p->cpu_control_mask);

    if (guard_changed || source_changed || reset_owner_mismatches)
        return NV_ERR_INVALID_STATE;
    p->result_flags |= CASK_IOVA_WRITE_CPU_COMPLETED;
    return NV_OK;
}

NV_STATUS uvm_test_cask_iova_write(UVM_TEST_CASK_IOVA_WRITE_PARAMS *p, struct file *filp)
{
    uvm_va_space_t *space = uvm_va_space_get(filp);
    uvm_gpu_t *gpus[2] = {NULL, NULL}, *gpu, *owner;
    NvProcessorUuid uuid;
    struct device *dev;
    struct iommu_domain *domain;
    uvm_mem_t *sys = NULL, *source_mem = NULL;
    uvm_rm_mem_t *target = NULL;
    uvm_gpu_address_t host_dma, source, source_readback_va, target_va, target_readback_va;
    NvU32 *cpu, *source_readback, *target_readback;
    void *target_cpu_va = NULL;
    resource_size_t bar_physical = 0, bar_start = 0, bar_length = 0;
    resource_size_t check_physical = 0, check_start = 0, check_length = 0;
    unsigned long resource_flags = 0, check_flags = 0;
    unsigned int page_level = 0, check_level = 0;
    int bar_index = -1, check_bar_index = -1;
    phys_addr_t host_physical, translated, translated_end;
    phys_addr_t check_translated, check_translated_end;
    dma_addr_t iova = 0;
    unsigned int i, mode, local_seq;
    bool pending = false, mapped = false, held = false, unmapped = false;
    NV_STATUS status = NV_ERR_INVALID_ARGUMENT;
    const char *phase = "entry";

    BUILD_BUG_ON(sizeof(*p) != 120);
    BUILD_BUG_ON(UVM_TEST_CASK_IOVA_WRITE != CASK_IOVA_WRITE_IOCTL);
    p->bar1_physical = 0;
    p->bar1_iova = 0;
    p->bar1_resource_start = 0;
    p->bar1_page_level = 0;
    p->domain_type = 0;
    p->host_pass_mask = 0;
    p->peer_pass_mask = 0;
    p->completed_mask = 0;
    p->result_flags = 0;
    p->alias_pass_mask = 0;
    p->rmStatus = 0;
    p->cpu_control_mask = 0;
    p->reserved_output = 0;

    if (!uvm_cask_iova_write || !capable(CAP_SYS_ADMIN))
        return NV_ERR_INSUFFICIENT_PERMISSIONS;
    if (p->abi_version != CASK_IOVA_WRITE_ABI || p->operation > 1 ||
        p->index > 1 || p->reserved || !p->request_id)
        return NV_ERR_INVALID_ARGUMENT;
    if (boot_cpu_data.x86_vendor != X86_VENDOR_INTEL ||
        boot_cpu_data.x86 != 6 || boot_cpu_data.x86_model != 0x9a ||
        boot_cpu_data.x86_stepping != 3 || boot_cpu_has(X86_FEATURE_HYPERVISOR) ||
        g_uvm_global.conf_computing_enabled || PAGE_SIZE != 4096)
        return NV_ERR_NOT_SUPPORTED;

    mutex_lock(&cask_iova_write_lock);
    if (cask_iova_write_fatal) {
        status = NV_ERR_INVALID_STATE;
        goto unlock;
    }

    uvm_mutex_lock(&g_uvm_global.global_lock);
    for (i = 0; i < 2; ++i) {
        memcpy(&uuid, p->gpu_uuid[i], 16);
        gpus[i] = uvm_gpu_get_by_uuid(&uuid);
        if (!cask_iova_write_gpu(gpus[i], i, p->gpu_uuid[i]))
            break;
    }
    if (i == 2) {
        uvm_gpu_retain(gpus[0]);
        uvm_gpu_retain(gpus[1]);
        held = true;
    }
    uvm_mutex_unlock(&g_uvm_global.global_lock);
    if (!held) {
        status = NV_ERR_INVALID_DEVICE;
        goto unlock;
    }

    gpu = gpus[p->index];
    owner = gpus[1 - p->index];
    dev = &gpu->parent->pci_dev->dev;
    uvm_va_space_down_read_rm(space);
    for (i = 0; i < 2; ++i) {
        memcpy(&uuid, p->gpu_uuid[i], 16);
        if (uvm_va_space_get_gpu_by_uuid_with_gpu_va_space(space, &uuid) != gpus[i]) {
            status = NV_ERR_INVALID_DEVICE;
            goto done;
        }
    }

    phase = "domain";
    domain = iommu_get_domain_for_dev(dev);
    if (!domain || domain->type != IOMMU_DOMAIN_DMA ||
        gpu->parent->rm_info.ceClass != AMPERE_DMA_COPY_B ||
        !gpu->parent->ce_phys_vidmem_write_supported ||
        gpu->parent->dma_addressable_start != 0) {
        status = NV_ERR_NOT_SUPPORTED;
        goto done;
    }
    p->domain_type = domain->type;
    p->result_flags = CASK_IOVA_WRITE_VALIDATED;
    if (!p->operation) {
        status = NV_OK;
        goto done;
    }
    if (cask_iova_write_used[p->index]) {
        status = NV_ERR_INVALID_STATE;
        goto done;
    }
    cask_iova_write_used[p->index] = true;

    phase = "allocations";
    status = uvm_mem_alloc_sysmem_and_map_cpu_kernel(3 * PAGE_SIZE, current->mm, &sys);
    if (status != NV_OK)
        goto done;
    for (i = 0; i < 2; ++i) {
        status = uvm_mem_map_gpu_kernel(sys, gpus[i]);
        if (status != NV_OK)
            goto done;
    }
    status = uvm_mem_alloc_vidmem(PAGE_SIZE, gpu, &source_mem);
    if (status != NV_OK)
        goto done;
    status = uvm_mem_map_gpu_kernel(source_mem, gpu);
    if (status != NV_OK)
        goto done;
    status = uvm_rm_mem_alloc_and_map_cpu(owner,
                                          UVM_RM_MEM_TYPE_GPU,
                                          PAGE_SIZE,
                                          PAGE_SIZE,
                                          &target);
    if (status != NV_OK)
        goto done;
    if (target->type != UVM_RM_MEM_TYPE_GPU || target->gpu_owner != owner ||
        target->size != PAGE_SIZE || !uvm_rm_mem_mapped_on_cpu(target) ||
        !uvm_rm_mem_mapped_on_gpu(target, owner)) {
        status = NV_ERR_INVALID_STATE;
        goto done;
    }

    cpu = uvm_mem_get_cpu_addr_kernel(sys);
    source_readback = (NvU32 *)((char *)cpu + PAGE_SIZE);
    target_readback = (NvU32 *)((char *)cpu + 2 * PAGE_SIZE);
    host_dma = uvm_mem_gpu_address_physical(sys, gpu, 0, PAGE_SIZE);
    source = uvm_mem_gpu_address_physical(source_mem, gpu, 0, PAGE_SIZE);
    source_readback_va = uvm_mem_gpu_address_virtual_kernel(sys, gpu);
    source_readback_va.address += PAGE_SIZE;
    target_readback_va = uvm_mem_gpu_address_virtual_kernel(sys, owner);
    target_readback_va.address += 2 * PAGE_SIZE;
    target_va = uvm_rm_mem_get_gpu_va(target, owner, false);
    target_cpu_va = uvm_rm_mem_get_cpu_va(target);

    if (!is_vmalloc_addr(cpu) || !vmalloc_to_page(cpu) ||
        host_dma.is_virtual || host_dma.aperture != UVM_APERTURE_SYS ||
        source.is_virtual || source.aperture != UVM_APERTURE_VID ||
        !target_va.is_virtual ||
        gpu->mem_info.max_allocatable_address < PAGE_SIZE - 1 ||
        source.address > gpu->mem_info.max_allocatable_address - (PAGE_SIZE - 1)) {
        status = NV_ERR_INVALID_STATE;
        goto done;
    }

    host_physical = page_to_phys(vmalloc_to_page(cpu));
    translated = iommu_iova_to_phys(domain, host_dma.address);
    if ((host_dma.address & 3) || translated != host_physical) {
        status = NV_ERR_INVALID_ADDRESS;
        goto done;
    }
    pr_info("CASKIOVAWRITE request=%llu index=%u stage=host_mapping executor=%s iova=%llx physical=%llx translated=%llx direction=DMA_BIDIRECTIONAL positive_control_only=1 valid=1\n",
            p->request_id,
            p->index,
            pci_name(gpu->parent->pci_dev),
            host_dma.address,
            (NvU64)host_physical,
            (NvU64)translated);

    phase = "resolve_bar1";
    if (!cask_iova_write_resolve_bar1(owner,
                                      target_cpu_va,
                                      &bar_physical,
                                      &bar_start,
                                      &bar_length,
                                      &page_level,
                                      &bar_index,
                                      &resource_flags)) {
        status = NV_ERR_INVALID_ADDRESS;
        goto done;
    }

    phase = "dma_map_resource";
    iova = dma_map_resource(dev, bar_physical, PAGE_SIZE, DMA_FROM_DEVICE, 0);
    if (dma_mapping_error(dev, iova)) {
        status = NV_ERR_NO_MEMORY;
        goto done;
    }
    mapped = true;
    translated = iommu_iova_to_phys(domain, iova);
    p->bar1_physical = bar_physical;
    p->bar1_iova = iova;
    p->bar1_resource_start = bar_start;
    p->bar1_page_level = page_level;
    p->result_flags |= CASK_IOVA_WRITE_MAPPED;
    if ((iova & (PAGE_SIZE - 1)) || iova == bar_physical ||
        gpu->parent->dma_addressable_limit < PAGE_SIZE - 1 ||
        iova > gpu->parent->dma_addressable_limit - (PAGE_SIZE - 1)) {
        status = NV_ERR_INVALID_ADDRESS;
        goto done;
    }
    translated_end = iommu_iova_to_phys(domain, iova + PAGE_SIZE - 1);
    pr_info("CASKIOVAWRITE request=%llu index=%u stage=mapping executor=%s owner=%s domain_type=%u bar_index=%d bar_start=%llx bar_length=%llx resource_flags=%lx cpu_pte_level=%u physical=%llx iova=%llx translated_first=%llx translated_last=%llx bytes=%lu direction=DMA_FROM_DEVICE private_target=1 rm_cpu_map=1 ordinary_peer_mapping=0\n",
            p->request_id,
            p->index,
            pci_name(gpu->parent->pci_dev),
            pci_name(owner->parent->pci_dev),
            domain->type,
            bar_index,
            (NvU64)bar_start,
            (NvU64)bar_length,
            resource_flags,
            page_level,
            (NvU64)bar_physical,
            (NvU64)iova,
            (NvU64)translated,
            (NvU64)translated_end,
            PAGE_SIZE);
    if (translated != bar_physical || translated_end != bar_physical + PAGE_SIZE - 1) {
        status = NV_ERR_INVALID_ADDRESS;
        goto done;
    }

    phase = "alias_check";
    status = cask_iova_write_alias_check(owner,
                                         p->index,
                                         p->request_id,
                                         target,
                                         target_readback_va,
                                         target_readback,
                                         target_cpu_va,
                                         p,
                                         &pending);
    if (status != NV_OK)
        goto done;

    phase = "writes";
    for (mode = 1; mode <= 2; ++mode) {
        NvU32 expected = cask_iova_write_source_pattern(p->index, mode);

        status = cask_iova_write_fill_read(gpu,
                                           source,
                                           source_readback_va,
                                           expected,
                                           &pending);
        if (status != NV_OK)
            goto done;
        if (cask_iova_write_mismatches(source_readback, expected, 0)) {
            status = NV_ERR_INVALID_STATE;
            goto done;
        }

        for (local_seq = 0; local_seq < 3; ++local_seq) {
            unsigned int seq = (mode - 1) * 3 + local_seq;

            status = cask_iova_write_one(gpu,
                                         owner,
                                         source,
                                         source_readback_va,
                                         source_readback,
                                         target_va,
                                         target_readback_va,
                                         target_readback,
                                         cpu,
                                         target_cpu_va,
                                         host_dma.address,
                                         iova,
                                         mode,
                                         seq,
                                         p->index,
                                         p,
                                         &pending);
            if (status != NV_OK)
                goto done;
        }
    }

    phase = "cpu_write_control";
    status = cask_iova_write_cpu_control(gpu,
                                         owner,
                                         source,
                                         source_readback_va,
                                         source_readback,
                                         target_va,
                                         target_readback_va,
                                         target_readback,
                                         target_cpu_va,
                                         p->index,
                                         p,
                                         &pending);
    if (status != NV_OK)
        goto done;

    phase = "mapping_stability";
    check_translated = iommu_iova_to_phys(domain, iova);
    check_translated_end = iommu_iova_to_phys(domain, iova + PAGE_SIZE - 1);
    if (!cask_iova_write_resolve_bar1(owner,
                                      target_cpu_va,
                                      &check_physical,
                                      &check_start,
                                      &check_length,
                                      &check_level,
                                      &check_bar_index,
                                      &check_flags) ||
        check_physical != bar_physical || check_start != bar_start ||
        check_length != bar_length || check_level != page_level ||
        check_bar_index != bar_index || check_flags != resource_flags ||
        check_translated != bar_physical ||
        check_translated_end != bar_physical + PAGE_SIZE - 1) {
        status = NV_ERR_INVALID_STATE;
        goto done;
    }
    pr_info("CASKIOVAWRITE request=%llu index=%u stage=mapping_stability physical=%llx iova_first_translation=%llx iova_last_translation=%llx unchanged=1 target_mapping_live=1\n",
            p->request_id,
            p->index,
            (NvU64)check_physical,
            (NvU64)check_translated,
            (NvU64)check_translated_end);
    p->result_flags |= CASK_IOVA_WRITE_COMPLETED;
    status = NV_OK;

done:
    if (pending) {
        cask_iova_write_fatal = true;
        __module_get(THIS_MODULE);
        p->result_flags |= CASK_IOVA_WRITE_RETAINED;
        cask_iova_write_held_gpus[0] = gpus[0];
        cask_iova_write_held_gpus[1] = gpus[1];
        cask_iova_write_held_sys = sys;
        cask_iova_write_held_source = source_mem;
        cask_iova_write_held_target = target;
        cask_iova_write_held_dma = iova;
        pr_err("CASKIOVAWRITE request=%llu stage=retained pending=1 all_dma_buffers_rm_mapping_and_gpus_retained_until_reboot=1\n",
               p->request_id);
    }
    else {
        if (mapped) {
            dma_unmap_resource(dev, iova, PAGE_SIZE, DMA_FROM_DEVICE, 0);
            unmapped = true;
            p->result_flags |= CASK_IOVA_WRITE_UNMAPPED;
        }
        uvm_rm_mem_free(target);
        uvm_mem_free(source_mem);
        uvm_mem_free(sys);
    }
    pr_info("CASKIOVAWRITE request=%llu index=%u stage=return operation=%u status=%x flags=%x alias_mask=%x host_mask=%x peer_mask=%x completed_mask=%x cpu_control_mask=%x pending=%u dma_unmapped=%u direction=DMA_FROM_DEVICE last_phase=%s\n",
            p->request_id,
            p->index,
            p->operation,
            status,
            p->result_flags,
            p->alias_pass_mask,
            p->host_pass_mask,
            p->peer_pass_mask,
            p->completed_mask,
            p->cpu_control_mask,
            pending,
            unmapped,
            phase);
    uvm_va_space_up_read_rm(space);
    if (!pending) {
        uvm_gpu_release(gpus[1]);
        uvm_gpu_release(gpus[0]);
    }

unlock:
    mutex_unlock(&cask_iova_write_lock);
    return status;
}
