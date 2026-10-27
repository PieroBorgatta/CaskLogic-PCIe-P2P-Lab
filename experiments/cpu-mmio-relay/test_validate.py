"""Mutation tests for the sanitized ABI5 result validator."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("abi5_validate", ROOT / "validate.py")
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class QualifiedResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = json.loads((ROOT / "qualified-result.json").read_text())

    def mutated(self):
        return deepcopy(self.baseline)

    def test_baseline(self):
        self.assertEqual(VALIDATOR.validate(self.baseline), [])

    def test_rejects_payload_mismatch(self):
        changed = self.mutated()
        changed["transfer"]["destination_mismatches"] = 1
        self.assertTrue(VALIDATOR.validate(changed))

    def test_rejects_ram_staging(self):
        changed = self.mutated()
        changed["memory"]["ram_staging"] = True
        self.assertTrue(VALIDATOR.validate(changed))

    def test_rejects_host_payload_buffer(self):
        changed = self.mutated()
        changed["memory"]["host_payload_buffer_during_relay"] = True
        self.assertTrue(VALIDATOR.validate(changed))

    def test_rejects_p2p_claim(self):
        changed = self.mutated()
        changed["classification"]["p2p_solution_claimed"] = True
        self.assertTrue(VALIDATOR.validate(changed))

    def test_rejects_performance_claim(self):
        changed = self.mutated()
        changed["classification"]["performance_claimed"] = True
        self.assertTrue(VALIDATOR.validate(changed))

    def test_rejects_timing_as_benchmark(self):
        changed = self.mutated()
        changed["single_diagnostic_timing"]["benchmark"] = True
        self.assertTrue(VALIDATOR.validate(changed))

    def test_rejects_private_identifiers(self):
        changed = self.mutated()
        changed["privacy"]["gpu_uuids_included"] = True
        self.assertTrue(VALIDATOR.validate(changed))


if __name__ == "__main__":
    unittest.main()
