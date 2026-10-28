"""Fail-closed route selection for the asymmetric two-GPU transport.

This module selects a transport; it does not claim that an API capability
query proves payload delivery.  Hardware startup tests remain mandatory for
the P2P and MMIO backends.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


PROTOCOL_VERSION = 1
MMIO_RELAY_ALIGNMENT = 64
MMIO_RELAY_MAX_BYTES = 4096
UINT64_MAX = (1 << 64) - 1


class GpuRole(IntEnum):
    ADA = 0
    A2000 = 1


class Route(IntEnum):
    """Values are shared with ``protocol.h`` and form a stable wire ABI."""

    P2P_FORWARD = 1
    MMIO_RELAY = 2
    RAM_STAGING = 3
    UNSUPPORTED_NO_FAST_PATH = 4


@dataclass(frozen=True)
class TransferRequest:
    source: GpuRole
    destination: GpuRole
    bytes: int
    allow_ram_staging: bool = False


@dataclass(frozen=True)
class Decision:
    route: Route
    reason: str
    pcie_p2p_requested: bool
    host_payload_buffer: bool


def _validated_role(value: GpuRole, field: str) -> GpuRole:
    if isinstance(value, bool) or not isinstance(value, (int, GpuRole)):
        raise ValueError(f"invalid {field} GPU role")
    try:
        return GpuRole(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid {field} GPU role") from error


def select_route(request: TransferRequest) -> Decision:
    """Select one explicit route without silently introducing host RAM.

    The fast path is deliberately one-way.  Reverse bulk traffic is rejected
    unless the caller opts in to RAM staging.  The CPU-MMIO route is bounded
    to control-size records; the backend must separately verify address
    alignment.  It is selected for no-RAM semantics, not throughput.
    """

    source = _validated_role(request.source, "source")
    destination = _validated_role(request.destination, "destination")
    if source == destination:
        raise ValueError("directional transport requires two different GPUs")
    if isinstance(request.bytes, bool) or not isinstance(request.bytes, int):
        raise ValueError("bytes must be an integer")
    if request.bytes <= 0 or request.bytes > UINT64_MAX:
        raise ValueError("bytes must fit a positive uint64")
    if not isinstance(request.allow_ram_staging, bool):
        raise ValueError("allow_ram_staging must be boolean")

    if source == GpuRole.A2000 and destination == GpuRole.ADA:
        return Decision(
            Route.P2P_FORWARD,
            "A2000-originated CUDA D2D PUSH is the qualified bulk direction",
            pcie_p2p_requested=True,
            host_payload_buffer=False,
        )

    # The only remaining valid cross-GPU direction is Ada -> A2000.
    if (request.bytes <= MMIO_RELAY_MAX_BYTES and
            request.bytes % MMIO_RELAY_ALIGNMENT == 0):
        return Decision(
            Route.MMIO_RELAY,
            "control-size record; backend must verify 64-byte address alignment",
            pcie_p2p_requested=False,
            host_payload_buffer=False,
        )

    if request.allow_ram_staging:
        return Decision(
            Route.RAM_STAGING,
            "caller explicitly allowed a host payload buffer fallback",
            pcie_p2p_requested=False,
            host_payload_buffer=True,
        )

    return Decision(
        Route.UNSUPPORTED_NO_FAST_PATH,
        "Ada-to-A2000 bulk has no fast no-RAM path on this topology",
        pcie_p2p_requested=False,
        host_payload_buffer=False,
    )

