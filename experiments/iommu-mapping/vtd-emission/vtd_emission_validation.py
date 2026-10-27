#!/usr/bin/env python3
"""Fail-closed replay for the sanitized ABI 4 VT-d emission record."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


FAULT = re.compile(
    r"DMAR: \[DMA Write NO_PASID\] Request device \[01:00\.0\] "
    r"fault addr <BAR1_IOVA> \[fault reason 0x05\] "
    r"PTE Write access is not set"
)


def fields(line: str, marker: str) -> dict[str, str]:
    if marker not in line:
        return {}
    return dict(
        token.split("=", 1)
        for token in line.split(marker, 1)[1].strip().split()
        if "=" in token
    )


def rows(text: str, marker: str) -> list[dict[str, str]]:
    return [fields(line, marker) for line in text.splitlines() if marker in line]


def one(text: str, marker: str, errors: list[str]) -> dict[str, str]:
    found = rows(text, marker)
    if len(found) != 1:
        errors.append(f"{marker.strip()}: expected one row, found {len(found)}")
        return {}
    return found[0]


def require(values: dict[str, str], expected: dict[str, str], label: str,
            errors: list[str]) -> None:
    for key, value in expected.items():
        if values.get(key) != value:
            errors.append(f"{label}: {key}={values.get(key)!r}, expected {value!r}")


def validate_log(result_log: str, kernel_log: str) -> dict[str, object]:
    errors: list[str] = []

    for literal in (
        "PUBLIC_REDACTION addresses_symbolized=1 identifiers_removed=1",
        "intel_iommu=on iommu.passthrough=0 iommu.strict=1",
        "External GPU tunnel established: 1",
        "VTD_EMISSION_PARAMETER=Y BUILTIN_TESTS_PARAMETER=1",
        "PEG_CCFG 00:01.0 04008077",
        "TCSS_CCFG 00:07.0 0e009077",
        "TCSS_CCFG 00:07.2 0e009077",
        "IOVA_DATA_DISKS_UNMOUNTED",
        "VTD_STAGE kind=bar1 request=401 launched=1",
        "SCRIPT_RC=0",
        "PROBE_COMPLETED",
    ):
        if literal not in result_log:
            errors.append(f"missing result marker: {literal}")

    begin = one(result_log, "VTD_EMISSION_BEGIN ", errors)
    require(begin, {
        "abi": "4", "mode": "bar1", "one_mode_per_process": "1",
        "requester": "0000:01:00.0", "dma_direction": "DMA_TO_DEVICE",
        "expected_fault_type": "DMA_Write_NO_PASID",
        "expected_reason": "05", "single_experimental_target_write": "1",
        "no_later_push": "1", "tracking_semaphore_release_expected": "1",
        "ordinary_peer_access": "0",
        "host_staging_for_peer": "0", "process_retention": "original",
        "no_fork": "1",
    }, "begin", errors)

    fd_selected = one(result_log, "VTD_EMISSION_FD_SELECTED ", errors)
    require(fd_selected, {
        "mode": "bar1", "matches": "1", "candidate_count": "2",
    }, "FD selection", errors)

    ioctl = one(result_log, "VTD_EMISSION_IOCTL ", errors)
    require(ioctl, {
        "mode": "bar1", "request": "401", "rv": "0", "errno": "0",
        "status": "0",
        "flags": "3ff", "domain": "3", "fault_kind": "1",
        "alias_mask": "f", "cpu_control_mask": "f",
        "ram_writable_mask": "f", "target_phys": "<BAR1_PHYS>",
        "target_iova": "<BAR1_IOVA>", "target_start": "<BAR1_START>",
        "target_pte_level": "1", "ram_phys": "0", "ram_iova": "0",
        "inputs_unchanged": "1",
    }, "ioctl", errors)

    end = one(result_log, "VTD_EMISSION_END ", errors)
    require(end, {
        "mode": "bar1", "process_returned": "0", "ioctl_returned": "1",
        "trap_armed": "1", "mapping_retained": "1",
        "protocol_complete": "1", "p2p_solution_claimed": "0",
    }, "end", errors)
    ready = one(result_log, "VTD_EMISSION_READY ", errors)
    require(ready, {
        "mode": "bar1", "request": "401", "ioctl_returned": "1",
        "process_parked": "1", "cuda_calls_after_trap": "0",
        "refs_held_until_reboot": "1",
    }, "ready", errors)
    process_state = one(result_log, "VTD_PROCESS_STATE ", errors)
    require(process_state, {
        "kind": "bar1", "request": "401", "ioctl_returned": "1",
        "parked": "1",
    }, "process state", errors)
    classification = one(result_log, "VTD_CLASSIFICATION ", errors)
    require(classification, {
        "status": "bar1_exact_vtd_permission_fault",
        "requester": "0000:01:00.0", "iova": "<BAR1_IOVA>",
        "reason": "05", "bar1_write_observed_at_vtd": "1",
        "bar1_write_reached_vtd": "1", "remote_delivery_proven": "0",
        "ram_control_launched": "0", "p2p_solution_claimed": "0",
    }, "classification", errors)
    health = rows(result_log, "VTD_PROCESS_HEALTH ")
    if len(health) != 2 or \
       {row.get("phase") for row in health} != {"after_observation", "before_final"}:
        errors.append("process health phases are incomplete")
    if any(
        row.get("kind") != "bar1" or row.get("request") != "401" or
        row.get("alive") != "1" or row.get("identity") != "1"
        for row in health
    ):
        errors.append("retained client health failed")

    gate = "CASKLOGIC_VTD_GATE_START kind=bar1 request=401"
    if kernel_log.count(gate) != 1:
        errors.append("BAR1 gate must occur exactly once")
        gated = kernel_log
    else:
        pre, gated = kernel_log.split(gate, 1)
        if re.search(r"DMAR:.*fault|NVRM: Xid|AER:|PCIe Bus Error:", pre,
                     re.IGNORECASE):
            errors.append("fault/error before BAR1 gate")

    stage_rows = rows(gated, "CASKVTDEMISSION ")
    expected_stages = [
        "preflight", "ram_positive_mapping", "source_preflight", "alias",
        "cpu_target_control", "ram_writable_control", "source_preflight",
        "readonly_mapping", "fault_arm", "retained", "return",
    ]
    stages = [row.get("stage") for row in stage_rows if row.get("request") == "401"]
    if stages != expected_stages:
        errors.append(f"driver stage sequence mismatch: {stages!r}")

    indexed: dict[str, list[dict[str, str]]] = {}
    for row in stage_rows:
        if row.get("request") == "401":
            indexed.setdefault(row.get("stage", ""), []).append(row)

    def stage(name: str) -> dict[str, str]:
        found = indexed.get(name, [])
        if len(found) != 1:
            errors.append(f"stage {name}: expected one row, found {len(found)}")
            return {}
        return found[0]

    require(stage("preflight"), {
        "requester": "0000:01:00.0", "owner": "0000:06:00.0",
        "domain_type": "3", "translation_required": "1",
        "requester_fixed": "1",
    }, "preflight", errors)
    require(stage("ram_positive_mapping"), {
        "requester": "0000:01:00.0", "iova": "<RAM_IOVA>",
        "physical": "<RAM_PHYS>", "translated": "<RAM_PHYS>",
        "direction": "DMA_BIDIRECTIONAL", "valid": "1",
    }, "RAM mapping", errors)
    sources = indexed.get("source_preflight", [])
    if len(sources) != 2 or any(
        row.get("executor") != "0000:01:00.0" or
        row.get("mismatches") != "0" or row.get("private_vidmem") != "1"
        for row in sources
    ) or len({row.get("expected") for row in sources}) != 2:
        errors.append("private source controls failed")
    require(stage("alias"), {
        "owner": "0000:06:00.0", "alias_mask": "f",
        "private_target": "1", "rm_cpu_map": "1", "alias_words": "16",
        "owner_a_mismatches": "0", "cpu_a_mismatches": "0",
        "owner_b_mismatches": "0", "cpu_b_mismatches": "0",
        "owner_reset_mismatches": "0", "cpu_reset_mismatches": "0",
    }, "alias", errors)
    require(stage("cpu_target_control"), {
        "executor": "0000:01:00.0", "owner": "0000:06:00.0",
        "owner_guard_changed": "0", "source_changed": "0",
        "owner_reset_mismatches": "0", "cpu_reset_mismatches": "0",
        "cpu_control_mask": "f", "ordering": "iowrite32_ioread32_flush",
        "owner_gpu_readback_primary": "1", "control_only": "1",
    }, "CPU BAR1 control", errors)
    writable = stage("ram_writable_control")
    require(writable, {
        "executor": "0000:01:00.0", "destination_iova": "<RAM_IOVA>",
        "guard_changed": "0", "source_changed": "0",
        "ram_writable_mask": "f", "direction": "DMA_BIDIRECTIONAL",
        "mode": "SYS1", "positive_control": "1",
    }, "writable RAM control", errors)
    if writable.get("actual") != writable.get("expected"):
        errors.append("writable RAM payload mismatch")
    require(stage("readonly_mapping"), {
        "kind": "bar1", "requester": "0000:01:00.0",
        "owner": "0000:06:00.0", "domain_type": "3", "bar_index": "1",
        "physical": "<BAR1_PHYS>", "iova": "<BAR1_IOVA>",
        "translated_first": "<BAR1_PHYS>",
        "translated_last": "<BAR1_LAST_PHYS>", "bytes": "4096",
        "direction": "DMA_TO_DEVICE", "cpu_pte_level": "1",
        "private_target": "1", "rm_cpu_map": "1",
    }, "read-only mapping", errors)
    require(stage("fault_arm"), {
        "kind": "bar1", "requester": "0000:01:00.0",
        "iova": "<BAR1_IOVA>", "bytes": "4", "mode": "SYS1",
        "direction": "DMA_TO_DEVICE", "expected_type": "DMA_Write_NO_PASID",
        "expected_reason": "05", "single_experimental_target_write": "1",
        "no_later_push": "1", "tracking_semaphore_release_expected": "1",
        "tracking_release_after_target_same_push": "1",
        "tracking_release_normally_writable": "1",
    }, "fault arm", errors)
    require(stage("retained"), {
        "kind": "bar1", "pending": "0", "armed": "1",
        "mapping_live": "1", "all_backing_objects_retained_until_reboot": "1",
        "watchdog_required": "1",
    }, "retention", errors)
    require(stage("return"), {
        "operation": "1", "status": "0", "flags": "3ff",
        "domain_type": "3", "fault_kind": "1", "alias_mask": "f",
        "cpu_control_mask": "f", "ram_writable_mask": "f",
        "pending": "0", "retained": "1", "direction": "DMA_TO_DEVICE",
        "last_phase": "fault_arm",
    }, "return", errors)

    fault_lines = [
        line for line in gated.splitlines()
        if "DMAR:" in line and "fault" in line.lower()
    ]
    exact_fault = len(fault_lines) == 1 and bool(
        FAULT.fullmatch(fault_lines[0].strip())
    )
    if not exact_fault:
        errors.append("expected one exact sanitized VT-d fault")
    elif "stage=fault_arm" not in gated:
        errors.append("fault arm marker absent")
        exact_fault = False
    elif gated.index(fault_lines[0]) < gated.index("stage=fault_arm"):
        errors.append("exact VT-d fault preceded the fault arm")
        exact_fault = False
    if re.search(r"NVRM: Xid|AER:|PCIe Bus Error:", kernel_log,
                 re.IGNORECASE):
        errors.append("mixed GPU/PCIe error record")
    if "CASKLOGIC_VTD_GATE_START kind=ram" in kernel_log or \
       "VTD_STAGE kind=ram" in result_log:
        errors.append("RAM read-only fallback launched after exact BAR1 fault")
    if re.search(r"remote_delivery_proven=1|p2p_solution_claimed=1",
                 result_log + kernel_log, re.IGNORECASE):
        errors.append("forbidden delivery/solution claim")

    complete = not errors
    return {
        "protocol_complete": complete,
        "status": "complete_bar1_exact_returned" if complete else "incomplete",
        "errors": errors,
        "fault": {
            "access": "DMA Write",
            "pasid": "NO_PASID",
            "requester": "01:00.0",
            "address": "<BAR1_IOVA>",
            "reason": "0x05",
            "explanation": "PTE Write access is not set",
        } if exact_fault else None,
        "controls": {
            "private_source_checks": "2/2",
            "bar1_alias_mask": "f",
            "cpu_bar1_control_mask": "f",
            "writable_ram_control_mask": "f",
            "mapping_retained_until_reboot": True,
            "ram_readonly_fallback_launched": False,
        } if complete else None,
        "bar1_write_observed_at_vtd": exact_fault,
        "bar1_write_reached_vtd": exact_fault,
        "remote_delivery_proven": False,
        "P2P_solution_claimed": False,
        "scope": (
            "The exact reason-0x05 record proves arrival at VT-d only; "
            "it does not prove downstream peer delivery."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result_log", type=Path)
    parser.add_argument("kernel_log", type=Path)
    args = parser.parse_args()
    result = validate_log(args.result_log.read_text(errors="replace"),
                          args.kernel_log.read_text(errors="replace"))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["protocol_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
