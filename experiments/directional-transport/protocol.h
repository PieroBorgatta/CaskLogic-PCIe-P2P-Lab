#ifndef CASKLOGIC_DIRECTIONAL_TRANSPORT_PROTOCOL_H
#define CASKLOGIC_DIRECTIONAL_TRANSPORT_PROTOCOL_H

#include <stdint.h>

#define CASK_DIRECTIONAL_PROTOCOL_VERSION 1U
#define CASK_DIRECTIONAL_MMIO_ALIGNMENT 64U
#define CASK_DIRECTIONAL_MMIO_MAX_BYTES 4096U
#define CASK_DIRECTIONAL_ACK_MAGIC UINT64_C(0x4341534b41434b31)

enum cask_directional_gpu_role {
    CASK_DIRECTIONAL_GPU_ADA = 0,
    CASK_DIRECTIONAL_GPU_A2000 = 1,
};

enum cask_directional_route {
    CASK_DIRECTIONAL_ROUTE_P2P_FORWARD = 1,
    CASK_DIRECTIONAL_ROUTE_MMIO_RELAY = 2,
    CASK_DIRECTIONAL_ROUTE_RAM_STAGING = 3,
    CASK_DIRECTIONAL_ROUTE_UNSUPPORTED_NO_FAST_PATH = 4,
};

enum cask_directional_request_flags {
    CASK_DIRECTIONAL_ALLOW_RAM_STAGING = 1U << 0,
};

struct cask_directional_request {
    uint32_t version;
    uint32_t source;
    uint32_t destination;
    uint32_t flags;
    uint64_t bytes;
    uint64_t reserved;
};

struct cask_directional_decision {
    uint32_t version;
    uint32_t route;
    uint32_t pcie_p2p_requested;
    uint32_t host_payload_buffer;
    uint64_t bytes;
    uint64_t reserved;
};

/* Exactly one cache line in size. The caller must provide a 64-byte-aligned
 * address. It is a control record, never a payload buffer.
 * The CPU-MMIO backend may relay it from Ada VRAM to A2000 VRAM after the
 * Ada consumer has completed a forward slot. The 64-byte copy is not atomic:
 * publish with magic=0, copy/fence/flush the body, then write and flush magic
 * last. A consumer accepts only the expected magic and sequence. */
struct cask_directional_ack {
    uint64_t magic;
    uint64_t sequence;
    uint64_t payload_bytes;
    uint64_t payload_checksum;
    uint32_t version;
    uint32_t queue;
    uint32_t slot;
    uint32_t status;
    uint64_t reserved[2];
};

#if defined(__cplusplus)
static_assert(sizeof(cask_directional_request) == 32, "request ABI size");
static_assert(sizeof(cask_directional_decision) == 32, "decision ABI size");
static_assert(sizeof(cask_directional_ack) == 64, "ack must be one cache line");
#else
_Static_assert(sizeof(struct cask_directional_request) == 32, "request ABI size");
_Static_assert(sizeof(struct cask_directional_decision) == 32, "decision ABI size");
_Static_assert(sizeof(struct cask_directional_ack) == 64, "ack must be one cache line");
#endif

#endif
