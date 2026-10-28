import json
from pathlib import Path
import unittest


class QualifiedResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = json.loads((Path(__file__).parent / "qualified-result.json").read_text())

    def test_scope_is_honest(self):
        self.assertFalse(self.result["bidirectional_p2p_fixed"])
        self.assertFalse(self.result["direct_route_proven"])
        self.assertIn("cross-run", self.result["comparison_scope"])

    def test_all_published_samples_are_correct(self):
        self.assertEqual(self.result["forward"]["payloads_correct"], 2)
        self.assertTrue(self.result["reverse_ram_staging"]["all_correct"])
        self.assertTrue(self.result["reverse_cpu_mmio"]["all_correct"])

    def test_ratios_recompute(self):
        forward = self.result["forward"]["median_logical_GB_s"]
        ram = self.result["reverse_ram_staging"]["median_logical_GB_s"]
        mmio = self.result["reverse_cpu_mmio"]["median_logical_GB_s"]
        self.assertAlmostEqual(self.result["ratios"]["forward_over_ram_staging"], forward / ram)
        self.assertAlmostEqual(self.result["ratios"]["forward_over_cpu_mmio"], forward / mmio)
        self.assertAlmostEqual(self.result["ratios"]["ram_staging_over_cpu_mmio"], ram / mmio)


if __name__ == "__main__":
    unittest.main()
