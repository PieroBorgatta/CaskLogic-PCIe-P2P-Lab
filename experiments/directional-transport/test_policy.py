"""Unit tests for the fail-closed directional transport policy."""

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("directional_policy", ROOT / "policy.py")
POLICY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = POLICY
SPEC.loader.exec_module(POLICY)


class DirectionalPolicyTests(unittest.TestCase):
    def decide(self, source, destination, size, allow_ram=False):
        return POLICY.select_route(POLICY.TransferRequest(
            source=source,
            destination=destination,
            bytes=size,
            allow_ram_staging=allow_ram,
        ))

    def test_forward_uses_p2p_for_small_and_bulk_payloads(self):
        for size in (1, 64, 4096, 16 * 1024 * 1024):
            with self.subTest(size=size):
                decision = self.decide(POLICY.GpuRole.A2000, POLICY.GpuRole.ADA, size)
                self.assertEqual(decision.route, POLICY.Route.P2P_FORWARD)
                self.assertTrue(decision.pcie_p2p_requested)
                self.assertFalse(decision.host_payload_buffer)

    def test_forward_does_not_stage_even_when_ram_is_allowed(self):
        decision = self.decide(
            POLICY.GpuRole.A2000, POLICY.GpuRole.ADA, 16 * 1024 * 1024, True)
        self.assertEqual(decision.route, POLICY.Route.P2P_FORWARD)

    def test_reverse_aligned_control_records_use_mmio_relay(self):
        for size in (64, 128, 1024, 4096):
            with self.subTest(size=size):
                decision = self.decide(POLICY.GpuRole.ADA, POLICY.GpuRole.A2000, size)
                self.assertEqual(decision.route, POLICY.Route.MMIO_RELAY)
                self.assertFalse(decision.pcie_p2p_requested)
                self.assertFalse(decision.host_payload_buffer)

    def test_reverse_unaligned_or_bulk_payload_is_rejected(self):
        for size in (1, 63, 65, 4095, 4097, 1024 * 1024):
            with self.subTest(size=size):
                decision = self.decide(POLICY.GpuRole.ADA, POLICY.GpuRole.A2000, size)
                self.assertEqual(decision.route, POLICY.Route.UNSUPPORTED_NO_FAST_PATH)
                self.assertFalse(decision.host_payload_buffer)

    def test_reverse_ram_staging_requires_explicit_opt_in(self):
        for size in (65, 4097, 16 * 1024 * 1024):
            with self.subTest(size=size):
                decision = self.decide(
                    POLICY.GpuRole.ADA, POLICY.GpuRole.A2000, size, allow_ram=True)
                self.assertEqual(decision.route, POLICY.Route.RAM_STAGING)
                self.assertTrue(decision.host_payload_buffer)
                self.assertFalse(decision.pcie_p2p_requested)

    def test_control_record_keeps_mmio_when_ram_fallback_is_allowed(self):
        decision = self.decide(
            POLICY.GpuRole.ADA, POLICY.GpuRole.A2000, 64, allow_ram=True)
        self.assertEqual(decision.route, POLICY.Route.MMIO_RELAY)
        self.assertFalse(decision.host_payload_buffer)

    def test_same_gpu_request_is_invalid(self):
        with self.assertRaisesRegex(ValueError, "different GPUs"):
            self.decide(POLICY.GpuRole.ADA, POLICY.GpuRole.ADA, 64)

    def test_invalid_sizes_fail_closed(self):
        for size in (0, -64, True, 64.0):
            with self.subTest(size=size), self.assertRaises(ValueError):
                self.decide(POLICY.GpuRole.ADA, POLICY.GpuRole.A2000, size)

    def test_invalid_role_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "invalid source"):
            self.decide(99, POLICY.GpuRole.ADA, 64)

    def test_boolean_roles_fail_closed(self):
        for role in (True, False):
            with self.subTest(role=role), self.assertRaises(ValueError):
                self.decide(role, POLICY.GpuRole.ADA, 64)

    def test_size_must_fit_wire_uint64(self):
        with self.assertRaisesRegex(ValueError, "uint64"):
            self.decide(POLICY.GpuRole.ADA, POLICY.GpuRole.A2000, 1 << 64)

    def test_non_boolean_ram_policy_fails_closed(self):
        request = POLICY.TransferRequest(
            POLICY.GpuRole.ADA, POLICY.GpuRole.A2000, 64, allow_ram_staging=1)
        with self.assertRaisesRegex(ValueError, "must be boolean"):
            POLICY.select_route(request)

    def test_protocol_values_are_stable(self):
        self.assertEqual(POLICY.PROTOCOL_VERSION, 1)
        self.assertEqual(POLICY.MMIO_RELAY_ALIGNMENT, 64)
        self.assertEqual(POLICY.MMIO_RELAY_MAX_BYTES, 4096)
        self.assertEqual(int(POLICY.GpuRole.ADA), 0)
        self.assertEqual(int(POLICY.GpuRole.A2000), 1)
        self.assertEqual(int(POLICY.Route.P2P_FORWARD), 1)
        self.assertEqual(int(POLICY.Route.MMIO_RELAY), 2)
        self.assertEqual(int(POLICY.Route.RAM_STAGING), 3)
        self.assertEqual(int(POLICY.Route.UNSUPPORTED_NO_FAST_PATH), 4)


if __name__ == "__main__":
    unittest.main()

