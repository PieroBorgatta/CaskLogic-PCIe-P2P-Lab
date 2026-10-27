"""Replay scoped published IOMMU records without accessing hardware."""

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CCFG = {
    "0000:00:01.0": (0, 0x04008077),
    "0000:00:07.0": (0, 0x0E009077),
    "0000:00:07.2": (0, 0x0E009077),
}


def load_validator(relative_path, module_name):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replay_result(directory, validator):
    result = validator.validate_log(
        (directory / "result-markers.log").read_text(),
        CCFG,
        (directory / "kernel-research.log").read_text(),
    )
    expected = json.loads((directory / "qualified.json").read_text())
    # Complete private collectors also checked files intentionally omitted from
    # the public package. Public replay compares the scoped scientific record.
    expected.pop("missing_expected_files", None)
    assert result == expected, (directory, result, expected)
    return result


status_validator = load_validator(
    "status/dmar_log_validation.py", "iommu_status_validation"
)
status = replay_result(ROOT / "status/results", status_validator)
assert status["protocol_complete"]
assert status["translation_inactive_in_all_samples"]
assert status["protected_regions_inactive_in_all_samples"]
print("Read-only IOMMU-off status: scoped records match the qualified result.")


read_validator = load_validator(
    "translated/iova_log_validation.py", "translated_bar0_read_validation"
)
translated_read = replay_result(ROOT / "translated/results", read_validator)
assert translated_read["protocol_complete"]
assert translated_read["host_controls_passed"] == 8
assert translated_read["peer_reads_passed"] == 0
read_attempt = replay_result(ROOT / "translated/attempt-01", read_validator)
assert not read_attempt["protocol_complete"]
print(
    "Translated BAR0 read: 8/8 RAM controls pass, 0/4 peer reads pass; "
    "the pre-GPU attempt remains incomplete."
)


write_validator = load_validator(
    "translated-write/write-only/iova_write_validation.py",
    "translated_private_bar1_write_validation",
)
write_result = replay_result(
    ROOT / "translated-write/write-only/results", write_validator
)
assert write_result["protocol_complete"]
assert write_result["host_controls_passed"] == 8
assert write_result["peer_writes_attempted"] == 4
assert write_result["peer_writes_passed"] == 2
assert write_result["ordinary_peer_mappings"] == 0
assert not write_result["host_staging_for_peer"]
assert not write_result["general_P2P_proven"]
write_masks = {
    executor["executor"]: executor["peer_pass_mask"]
    for executor in write_result["executors"]
}
assert write_masks == {"0000:06:00.0": 3, "0000:01:00.0": 0}
assert all(
    executor["mapping_stable"] and executor["dma_mapping_unmapped"]
    for executor in write_result["executors"]
)
write_attempt = replay_result(
    ROOT / "translated-write/write-only/attempt-01", write_validator
)
assert not write_attempt["protocol_complete"]
print(
    "Translated private BAR1 write ABI 1: 8/8 RAM controls and 2/4 "
    "cross-GPU writes pass; the pre-GPU attempt remains incomplete."
)


cpu_validator = load_validator(
    "translated-write/cpu-control/iova_write_validation.py",
    "translated_private_bar1_cpu_control_validation",
)
cpu_result = replay_result(
    ROOT / "translated-write/cpu-control/results", cpu_validator
)
assert cpu_result["protocol_complete"]
assert cpu_result["host_controls_passed"] == 8
assert cpu_result["peer_writes_attempted"] == 4
assert cpu_result["peer_writes_passed"] == 2
assert cpu_result["cpu_bar1_controls_attempted"] == 2
assert cpu_result["cpu_bar1_controls_passed"] == 2
assert cpu_result["cpu_bar1_control_after_peer_results"]
assert not cpu_result["cpu_bar1_control_is_p2p"]
assert not cpu_result["general_P2P_proven"]
cpu_peer_masks = {
    executor["executor"]: executor["peer_pass_mask"]
    for executor in cpu_result["executors"]
}
assert cpu_peer_masks == {"0000:06:00.0": 3, "0000:01:00.0": 0}
assert all(
    executor["cpu_bar1_control"]["mask"] == 0xF
    and executor["cpu_bar1_control"]["passed_owner_gpu_primary"]
    and not executor["cpu_bar1_control"]["is_p2p"]
    for executor in cpu_result["executors"]
)
print(
    "Translated private BAR1 write ABI 2: the 2/4 peer matrix is unchanged; "
    "2/2 post-peer CPU controls pass and are not P2P."
)


self_validator = load_validator(
    "translated-write/self-loop/iova_write_validation.py",
    "translated_private_bar1_self_loop_validation",
)
self_result = replay_result(
    ROOT / "translated-write/self-loop/results", self_validator
)
assert self_result["protocol_complete"]
assert self_result["host_controls_passed"] == 8
assert self_result["self_bar1_writes_attempted"] == 4
assert self_result["self_bar1_writes_passed"] == 0
assert self_result["cross_gpu_peer_transfers"] == 0
assert self_result["cpu_bar1_controls_attempted"] == 2
assert self_result["cpu_bar1_controls_passed"] == 2
assert self_result["inter_gpu_async_fault_gate_passed"]
assert not self_result["cpu_bar1_control_is_p2p"]
assert not self_result["general_P2P_proven"]
assert all(
    executor["self_pass_mask"] == 0
    and executor["cpu_bar1_control"]["mask"] == 0xF
    and executor["cpu_bar1_control"]["passed_owner_gpu_primary"]
    and not executor["cpu_bar1_control"]["is_p2p"]
    for executor in self_result["executors"]
)
print(
    "Translated private BAR1 ABI 3: 8/8 RAM and 2/2 non-P2P CPU controls "
    "pass, 0/4 self writes pass, and the clean gate covers zero cross-GPU "
    "transfers; self-hairpin is not a peer-route diagnosis."
)


vtd_validator = load_validator(
    "vtd-emission/vtd_emission_validation.py",
    "vtd_emission_validation",
)
vtd_directory = ROOT / "vtd-emission/results"
vtd_result = vtd_validator.validate_log(
    (vtd_directory / "result-markers.log").read_text(),
    (vtd_directory / "kernel-research.log").read_text(),
)
vtd_expected = json.loads((vtd_directory / "qualified.json").read_text())
assert vtd_result == vtd_expected, (vtd_result, vtd_expected)
assert vtd_result["protocol_complete"]
assert vtd_result["status"] == "complete_bar1_exact_returned"
assert vtd_result["bar1_write_reached_vtd"]
assert not vtd_result["remote_delivery_proven"]
assert not vtd_result["P2P_solution_claimed"]
print(
    "VT-d emission ABI 4: one Ada DMA Write NO_PASID reached VT-d and "
    "faulted on the intentional read-only BAR1 mapping; downstream remote "
    "delivery remains unproven."
)
