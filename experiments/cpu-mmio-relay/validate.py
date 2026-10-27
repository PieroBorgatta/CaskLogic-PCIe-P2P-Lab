#!/usr/bin/env python3
"""Fail-closed validation of the sanitized ABI5 result."""

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
RESULT = ROOT / "qualified-result.json"


def validate(result):
    """Return a list of qualification errors; an empty list means qualified."""
    errors = []

    expected_top_level = {
        "schema",
        "experiment",
        "date",
        "status",
        "protocol_complete",
        "errors",
        "transfer",
        "memory",
        "classification",
        "single_diagnostic_timing",
        "controls",
        "limitations",
        "privacy",
    }
    if set(result) != expected_top_level:
        errors.append("top-level schema")

    scalar_contract = {
        "schema": "casklogic.cpu-mmio-relay.qualified-result.v1",
        "experiment": "ABI5 CPU-MMIO BAR1 relay",
        "date": "2026-10-28",
        "status": "qualified_host_mediated_workaround",
        "protocol_complete": True,
        "errors": [],
    }
    for key, expected in scalar_contract.items():
        if result.get(key) != expected:
            errors.append(key)

    transfer = result.get("transfer", {})
    expected_transfer = {
        "correct": True,
        "bytes": 4096,
        "words": 1024,
        "source": (
            "private internal-GPU VRAM exposed through a driver-managed "
            "BAR1 mapping"
        ),
        "destination": (
            "private external-GPU VRAM exposed through a driver-managed "
            "BAR1 mapping"
        ),
        "path": "CPU MMIO load -> general-purpose register -> CPU MMIO store",
        "source_mismatches": 0,
        "destination_mismatches": 0,
        "guard_mismatches": 0,
    }
    if transfer != expected_transfer:
        errors.append("transfer contract")

    if result.get("memory") != {
        "host_payload_buffer_during_relay": False,
        "validation_buffer_allocated_after_relay": True,
        "ram_staging": False,
    }:
        errors.append("memory contract")

    if result.get("classification") != {
        "host_initiated": True,
        "pcie_p2p": False,
        "p2p_solution_claimed": False,
        "performance_claimed": False,
    }:
        errors.append("classification contract")

    timing = result.get("single_diagnostic_timing", {})
    if (
        set(timing) != {"elapsed_ns", "approx_MB_s", "benchmark"}
        or timing.get("elapsed_ns") != 697839
        or timing.get("benchmark") is not False
        or abs(timing.get("approx_MB_s", 0) - 5.869548706793402) > 1e-12
    ):
        errors.append("single diagnostic timing")

    if result.get("controls") != {
        "private_allocations": True,
        "owner_gpu_readback": True,
        "cpu_secondary_readback": True,
        "guards_intact": True,
        "runtime_restored": True,
        "new_xid_dmar_aer_in_scope": False,
    }:
        errors.append("controls")

    expected_limitations = [
        "The payload was moved by CPU MMIO load/store operations, not by a GPU peer transaction.",
        "The result does not repair or qualify bidirectional PCIe P2P.",
        "One 4 KiB diagnostic timing is not a performance benchmark.",
        "The unsupported PEG-to-TCSS route is identified; the exact internal silicon block is not exposed.",
    ]
    if result.get("limitations") != expected_limitations:
        errors.append("limitations")

    if result.get("privacy") != {
        "gpu_uuids_included": False,
        "bus_or_physical_addresses_included": False,
        "private_paths_included": False,
        "binaries_or_kernel_modules_included": False,
        "nvidia_derived_source_included": False,
    }:
        errors.append("privacy contract")

    return errors


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) > 1:
        raise SystemExit("usage: validate.py [qualified-result.json]")
    path = Path(argv[0]) if argv else RESULT
    result = json.loads(path.read_text())
    errors = validate(result)
    if errors:
        print(json.dumps({"qualified": False, "errors": errors}, indent=2))
        return 1
    print(json.dumps({"qualified": True, "errors": []}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
