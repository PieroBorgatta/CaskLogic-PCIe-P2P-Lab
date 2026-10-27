#ifndef CASK_IOVA_WRITE_IOCTL_H
#define CASK_IOVA_WRITE_IOCTL_H

#ifdef __KERNEL__
#include <linux/types.h>
typedef __u8 cask_w8;
typedef __u32 cask_w32;
typedef __u64 cask_w64;
#else
#include <stdint.h>
typedef uint8_t cask_w8;
typedef uint32_t cask_w32;
typedef uint64_t cask_w64;
#endif

#define CASK_IOVA_WRITE_IOCTL 318U
#define CASK_IOVA_WRITE_ABI 3U

#define CASK_IOVA_WRITE_VALIDATED      (1U << 0)
#define CASK_IOVA_WRITE_MAPPED         (1U << 1)
#define CASK_IOVA_WRITE_SUBMITTED      (1U << 2)
#define CASK_IOVA_WRITE_COMPLETED      (1U << 3)
#define CASK_IOVA_WRITE_UNMAPPED       (1U << 4)
#define CASK_IOVA_WRITE_RETAINED       (1U << 5)
#define CASK_IOVA_WRITE_ALIAS_VERIFIED (1U << 6)
#define CASK_IOVA_WRITE_CPU_COMPLETED  (1U << 7)

/* No physical addresses, RM handles or user buffers are inputs. operation=0
 * validates identities and the translated requester domain only. operation=1
 * performs six bounded four-byte writes: RAM, the requester's own private BAR1
 * target, RAM for each of SYS1 and SYS2. Only after those self-loop results it
 * performs a
 * one-word CPU-write control on the same live RM BAR1 mapping and restores the
 * private target through the owner GPU. The first 56 bytes are immutable input.
 * cpu_control_mask: bit 0 owner-GPU write observation, bit 1 secondary CPU
 * observation, bit 2 owner-GPU reset verification, bit 3 secondary CPU reset. */
typedef struct __attribute__((aligned(8))) {
    cask_w32 abi_version, operation, index, reserved;
    cask_w64 request_id;
    cask_w8 gpu_uuid[2][16];

    cask_w64 bar1_physical, bar1_iova, bar1_resource_start;
    cask_w32 bar1_page_level, domain_type;
    cask_w32 host_pass_mask, self_pass_mask, completed_mask;
    cask_w32 result_flags, alias_pass_mask, rmStatus;
    cask_w32 cpu_control_mask, reserved_output;
} UVM_TEST_CASK_IOVA_WRITE_PARAMS;

#endif
