#ifndef CASK_IOVA_MMIO_IOCTL_H
#define CASK_IOVA_MMIO_IOCTL_H
#ifdef __KERNEL__
#include <linux/types.h>
typedef __u8 cask_i8;
typedef __u32 cask_i32;
typedef __u64 cask_i64;
#else
#include <stdint.h>
typedef uint8_t cask_i8;
typedef uint32_t cask_i32;
typedef uint64_t cask_i64;
#endif
#define CASK_IOVA_IOCTL 317U
#define CASK_IOVA_ABI 1U
#define CASK_IOVA_VALIDATED 1U
#define CASK_IOVA_SUBMITTED 2U
#define CASK_IOVA_COMPLETED 4U
#define CASK_IOVA_RETAINED 8U
/* No addresses, RM handles or user buffers are accepted. operation=0 checks
 * identity/domain only. operation=1 runs six bounded 4-byte reads. */
typedef struct __attribute__((aligned(8))) {
    cask_i32 abi_version, operation, index, reserved;
    cask_i64 request_id;
    cask_i8 gpu_uuid[2][16];
    cask_i64 mmio_iova, mmio_physical;
    cask_i32 domain_type, host_pass_mask, peer_pass_mask, completed_mask;
    cask_i32 result_flags, rmStatus;
} UVM_TEST_CASK_IOVA_MMIO_PARAMS;
#endif
