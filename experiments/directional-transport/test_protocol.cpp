#include "protocol.h"

#include <cstddef>

static_assert(CASK_DIRECTIONAL_PROTOCOL_VERSION == 1U);
static_assert(CASK_DIRECTIONAL_MMIO_ALIGNMENT == 64U);
static_assert(CASK_DIRECTIONAL_MMIO_MAX_BYTES == 4096U);
static_assert(CASK_DIRECTIONAL_ACK_MAGIC == UINT64_C(0x4341534b41434b31));
static_assert(offsetof(cask_directional_ack, magic) == 0);
static_assert(offsetof(cask_directional_ack, sequence) == 8);
static_assert(offsetof(cask_directional_ack, version) == 32);
static_assert(offsetof(cask_directional_ack, reserved) == 48);

int main()
{
    cask_directional_ack ack{};
    ack.magic = CASK_DIRECTIONAL_ACK_MAGIC;
    ack.version = CASK_DIRECTIONAL_PROTOCOL_VERSION;
    return ack.magic == CASK_DIRECTIONAL_ACK_MAGIC &&
                   ack.version == CASK_DIRECTIONAL_PROTOCOL_VERSION ?
           0 : 1;
}
