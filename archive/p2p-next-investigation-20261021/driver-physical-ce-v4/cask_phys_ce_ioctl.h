#ifndef CASK_PHYS_CE_IOCTL_H
#define CASK_PHYS_CE_IOCTL_H
/* Diagnostic ABI v1, Linux x86_64 only. No input physical addresses/handles.
 * Use only the CUDA-owned /dev/nvidia-uvm FD found in /proc/self/fd.
 * VALIDATE does not submit a GPU operation. EXECUTE revalidates under lock.
 * If RETAINED is set, stop this native trial and reboot: objects stay pinned.
 */
#ifdef __KERNEL__
#include <linux/types.h>
typedef __u8 cask_ce_u8;
typedef __u32 cask_ce_u32;
typedef __u64 cask_ce_u64;
#else
#include <stdint.h>
typedef uint8_t cask_ce_u8;
typedef uint32_t cask_ce_u32;
typedef uint64_t cask_ce_u64;
#endif
#define CASK_PHYS_CE_IOCTL 315U /* UVM_TEST_IOCTL_BASE(115), Linux */
#define CASK_PHYS_CE_ABI 1U
#define CASK_PHYS_CE_VALIDATE 0U
#define CASK_PHYS_CE_EXECUTE 1U
#define CASK_PHYS_CE_VALIDATED 0x01U
#define CASK_PHYS_CE_SUBMITTED 0x02U
#define CASK_PHYS_CE_COMPLETED 0x04U
#define CASK_PHYS_CE_RETAINED 0x08U
#define CASK_PHYS_CE_P2P_CHANNEL 0x10U
#define CASK_PHYS_CE_PRIVILEGED 0x20U
#define CASK_PHYS_CE_NO_VIRTUAL_FALLBACK 0x40U
#define CASK_PHYS_CE_SUCCESS_FLAGS 0x77U
/* Exactly144bytes; UUID bytes match CUDA's16-byte UUID (no string punctuation). */
typedef struct __attribute__((aligned(8))) {
    cask_ce_u32 abi_version;
    cask_ce_u32 operation;
    cask_ce_u64 request_id;
    cask_ce_u8 source_uuid[16];
    cask_ce_u8 destination_uuid[16];
    cask_ce_u64 source_va;
    cask_ce_u64 destination_va;
    cask_ce_u32 bytes;
    cask_ce_u32 reserved;
    /* Outputs below; kernel resets every output on entry. */
    cask_ce_u64 source_physical;
    cask_ce_u64 destination_physical;
    cask_ce_u64 source_allocation_offset;
    cask_ce_u64 destination_allocation_offset;
    cask_ce_u32 source_rm_handle;
    cask_ce_u32 destination_rm_handle;
    cask_ce_u32 ce_class;
    cask_ce_u32 launch_dma;
    cask_ce_u32 source_phys_mode;
    cask_ce_u32 destination_phys_mode;
    cask_ce_u32 result_flags;
    cask_ce_u32 rmStatus;
    cask_ce_u64 reserved_out;
} UVM_TEST_CASK_PHYSICAL_CE_PARAMS;
#if defined(__cplusplus)
static_assert(sizeof(UVM_TEST_CASK_PHYSICAL_CE_PARAMS)==144,"physical CE ABI");
#elif !defined(__KERNEL__)
_Static_assert(sizeof(UVM_TEST_CASK_PHYSICAL_CE_PARAMS)==144,"physical CE ABI");
#endif
#endif
