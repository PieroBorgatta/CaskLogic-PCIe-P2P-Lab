import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "vtd_emission_validation", HERE / "vtd_emission_validation.py"
)
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)
RAW = (HERE / "results/result-markers.log").read_text()
KERNEL = (HERE / "results/kernel-research.log").read_text()


class VtdEmissionValidationTests(unittest.TestCase):
    def assert_incomplete(self, raw=RAW, kernel=KERNEL):
        result = VALIDATOR.validate_log(raw, kernel)
        self.assertFalse(result["protocol_complete"])
        self.assertEqual(result["status"], "incomplete")
        self.assertTrue(result["errors"])

    def test_published_record_qualifies(self):
        result = VALIDATOR.validate_log(RAW, KERNEL)
        self.assertTrue(result["protocol_complete"])
        self.assertEqual(result["status"], "complete_bar1_exact_returned")
        self.assertTrue(result["bar1_write_reached_vtd"])
        self.assertFalse(result["remote_delivery_proven"])
        self.assertFalse(result["P2P_solution_claimed"])

    def test_rejects_wrong_requester(self):
        self.assert_incomplete(kernel=KERNEL.replace("[01:00.0]", "[06:00.0]"))

    def test_rejects_read_fault(self):
        self.assert_incomplete(kernel=KERNEL.replace("DMA Write", "DMA Read"))

    def test_rejects_pasid_fault(self):
        self.assert_incomplete(kernel=KERNEL.replace("NO_PASID", "PASID 0001"))

    def test_rejects_wrong_iova(self):
        self.assert_incomplete(kernel=KERNEL.replace(
            "fault addr <BAR1_IOVA>", "fault addr <OTHER_IOVA>"
        ))

    def test_rejects_wrong_reason(self):
        self.assert_incomplete(kernel=KERNEL.replace("reason 0x05", "reason 0x06"))

    def test_rejects_wrong_fault_text(self):
        self.assert_incomplete(kernel=KERNEL.replace(
            "PTE Write access is not set", "PTE Read access is not set"
        ))

    def test_rejects_missing_ram_control(self):
        kernel = "\n".join(
            line for line in KERNEL.splitlines()
            if "stage=ram_writable_control" not in line
        )
        self.assert_incomplete(kernel=kernel)

    def test_rejects_missing_end_but_preserves_fault_observation(self):
        raw = "\n".join(
            line for line in RAW.splitlines()
            if "VTD_EMISSION_END " not in line
        )
        result = VALIDATOR.validate_log(raw, KERNEL)
        self.assertFalse(result["protocol_complete"])
        self.assertTrue(result["bar1_write_reached_vtd"])
        self.assertIsNone(result["controls"])

    def test_rejects_missing_unique_fd_selection(self):
        raw = "\n".join(
            line for line in RAW.splitlines()
            if "VTD_EMISSION_FD_SELECTED " not in line
        )
        self.assert_incomplete(raw=raw)

    def test_rejects_bad_process_state(self):
        self.assert_incomplete(raw=RAW.replace(
            "VTD_PROCESS_STATE kind=bar1 request=401 ioctl_returned=1 parked=1",
            "VTD_PROCESS_STATE kind=bar1 request=401 ioctl_returned=0 parked=1",
        ))

    def test_rejects_duplicate_health_phase(self):
        line = next(
            line for line in RAW.splitlines()
            if "VTD_PROCESS_HEALTH " in line
        )
        self.assert_incomplete(raw=RAW + line + "\n")

    def test_rejects_failed_alias_control(self):
        self.assert_incomplete(kernel=KERNEL.replace("alias_mask=f", "alias_mask=0", 1))

    def test_rejects_source_corruption(self):
        self.assert_incomplete(kernel=KERNEL.replace("mismatches=0", "mismatches=1", 1))

    def test_rejects_pre_gate_fault(self):
        self.assert_incomplete(kernel=(
            "DMAR: synthetic pre-gate fault\n" + KERNEL
        ))

    def test_rejects_mixed_pcie_error(self):
        self.assert_incomplete(kernel=KERNEL + "AER: synthetic uncorrected error\n")

    def test_rejects_fault_before_arm(self):
        fault = next(line for line in KERNEL.splitlines() if line.startswith("DMAR:"))
        lines = [line for line in KERNEL.splitlines() if line != fault]
        gate = next(
            i for i, line in enumerate(lines)
            if line.startswith("CASKLOGIC_VTD_GATE_START")
        )
        lines.insert(gate + 1, fault)
        self.assert_incomplete(kernel="\n".join(lines))

    def test_rejects_ram_fallback_after_exact_fault(self):
        self.assert_incomplete(kernel=(
            KERNEL + "CASKLOGIC_VTD_GATE_START kind=ram request=402\n"
        ))

    def test_rejects_remote_delivery_claim(self):
        self.assert_incomplete(raw=RAW.replace(
            "remote_delivery_proven=0", "remote_delivery_proven=1"
        ))

    def test_rejects_stage_reordering(self):
        lines = KERNEL.splitlines()
        alias = next(i for i, line in enumerate(lines) if "stage=alias " in line)
        control = next(i for i, line in enumerate(lines) if "stage=cpu_target_control " in line)
        lines[alias], lines[control] = lines[control], lines[alias]
        self.assert_incomplete(kernel="\n".join(lines))


if __name__ == "__main__":
    unittest.main()
