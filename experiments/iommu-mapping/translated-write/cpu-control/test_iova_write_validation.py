"""Synthetic protocol fixtures only; these are not hardware measurements."""
import unittest

from iova_write_validation import (alias_pattern_a, alias_pattern_b,
                                   cpu_pattern, cpu_sentinel, host_sentinel, source_pattern,
                                   target_sentinel, validate_log)


CCFG = {
    "0000:00:01.0": (0, 0x04008077),
    "0000:00:07.0": (0, 0x0e009077),
    "0000:00:07.2": (0, 0x0e009077),
}


def fixture(peer_masks=None, alias_diverges=False, cpu_owner_pass=None,
            cpu_alias_diverges=False, cpu_reset_secondary_pass=None):
    """Return one complete synthetic run.

    peer_masks maps executor index to the two SYS-mode result bits. A missing
    map models the useful complete-negative 0/4 hardware result. cpu_owner_pass
    independently models the two topology controls; neither is counted as P2P.
    """
    peer_masks = dict(peer_masks or {1: 0, 0: 0})
    cpu_owner_pass = dict(cpu_owner_pass or {1: True, 0: True})
    cpu_reset_secondary_pass = dict(cpu_reset_secondary_pass or {1: True, 0: True})
    raw = (
        "intel_iommu=on iommu.passthrough=0 iommu.strict=1\n"
        "IOVA_WRITE_PARAMETER=Y BUILTIN_TESTS_PARAMETER=1\n"
        "IOVA_DMAR_BEFORE_BEGIN\nIOVA_DMAR_BEFORE_END\n"
        "IOVA_WRITE_BEGIN abi=2 private_rm_vidmem_target=1 "
        "dma_direction=DMA_FROM_DEVICE peer_writes_only=1 ordinary_peer_access=0 "
        "host_staging_for_peer=0 owner_gpu_readback_primary=1 "
        "cpu_write_control_after_peer=1 cpu_control_is_p2p=0\n"
        "IOVA_WRITE_GPU index=0 bdf=0000:01:00.0 local_registration_bytes=65536 "
        "peer_mapping=0\n"
        "IOVA_WRITE_GPU index=1 bdf=0000:06:00.0 local_registration_bytes=65536 "
        "peer_mapping=0\n"
        "IOVA_WRITE_FD_SELECTED matches=1 candidate_count=3\n"
    )
    for _ in range(3):
        for bdf, (_, value) in CCFG.items():
            marker = "PEG_CCFG" if bdf.endswith("01.0") else "TCSS_CCFG"
            raw += "%s %s %08x\n" % (marker, bdf[5:], value)

    kernel = ""
    for _ in range(2):
        kernel += (
            "CASKDMAR_BEGIN version=1 units=1 table_bytes=80 register_writes=0\n"
            "CASKDMAR_CAP base=fed91000 ver=00000050 cap=00d2008c40660462 "
            "ecap=0000000000f050da\n"
        )
        for sample in range(2):
            kernel += (
                "CASKDMAR_SAMPLE index=%d gsts=c7000000 pmen=00000000 "
                "translation_enabled=1 interrupt_remapping_enabled=1 "
                "protected_region_enabled=0 protected_region_status=0\n" % sample
            )
        kernel += (
            "CASKDMAR_END protocol_complete=1 register_writes=0\n"
            "CASKDMAR_UNLOADED register_writes=0\n"
        )

    geometry = {
        1: {"request": 201, "iova": 0xfe100000, "physical": 0x62001000,
            "bar_start": 0x60000000, "host_iova": 0xf0100000,
            "executor": "0000:06:00.0", "owner": "0000:01:00.0"},
        0: {"request": 202, "iova": 0xfe000000, "physical": 0x52002000,
            "bar_start": 0x50000000, "host_iova": 0xf0000000,
            "executor": "0000:01:00.0", "owner": "0000:06:00.0"},
    }
    for index in (1, 0):
        item = geometry[index]
        prefix = "CASKIOVAWRITE request=%d index=%d " % (item["request"], index)
        kernel += prefix + (
            "stage=host_mapping executor=%s iova=%x physical=%x translated=%x "
            "direction=DMA_BIDIRECTIONAL positive_control_only=1 valid=1\n" %
            (item["executor"], item["host_iova"], 0x120000000 + index * 0x1000,
             0x120000000 + index * 0x1000)
        )
        kernel += prefix + (
            "stage=mapping executor=%s owner=%s domain_type=3 bar_index=1 "
            "bar_start=%x bar_length=10000000 resource_flags=2200 cpu_pte_level=1 "
            "physical=%x iova=%x translated_first=%x translated_last=%x bytes=4096 "
            "direction=DMA_FROM_DEVICE private_target=1 rm_cpu_map=1 "
            "ordinary_peer_mapping=0\n" %
            (item["executor"], item["owner"], item["bar_start"], item["physical"],
             item["iova"], item["physical"], item["physical"] + 4095)
        )
        pattern_a = alias_pattern_a(index)
        pattern_b = alias_pattern_b(index)
        reset = target_sentinel(index, 0)
        kernel += prefix + (
            "stage=alias owner=%s private_target=1 rm_cpu_map=1 alias_words=16 "
            "owner_a_mismatches=0 cpu_a=%08x cpu_a_mismatches=0 expected_a=%08x "
            "owner_b_mismatches=0 cpu_b=%08x cpu_b_mismatches=0 expected_b=%08x "
            "owner_reset_mismatches=0 cpu_reset=%08x cpu_reset_mismatches=0 "
            "alias_mask=f\n" %
            (item["owner"], pattern_a, pattern_a, pattern_b, pattern_b, reset)
        )
        mask = peer_masks.get(index, 0)
        for seq in range(6):
            mode = 1 + seq // 3
            peer = seq % 3 == 1
            expected = source_pattern(index, mode)
            sentinel = (target_sentinel(index, mode) if peer else
                        host_sentinel(index, mode, seq))
            matched = not peer or bool(mask & (1 << (mode - 1)))
            actual = expected if matched else sentinel
            alias_actual = actual if peer else 0
            alias_match = int(peer and alias_actual == expected)
            alias_guards = 0
            if peer and alias_diverges:
                alias_actual = sentinel
                alias_match = 0
                alias_guards = 3
            kernel += prefix + (
                "stage=result seq=%d mode=%d kind=%s destination_iova=%x bytes=4 "
                "expected=%08x actual=%08x sentinel=%08x match=%d guard_changed=0 "
                "source_changed=0 owner_gpu_readback=%d alias_actual=%08x "
                "alias_match=%d alias_guard_changed=%d class=c7b5 launch=4003186 "
                "p2p_channel=0 privileged=1 host_relay=0\n" %
                (seq, mode, "peer_bar1" if peer else "host_ram",
                 item["iova"] if peer else item["host_iova"], expected, actual,
                 sentinel, int(actual == expected), int(peer), alias_actual,
                 alias_match, alias_guards)
            )
        control_pattern = cpu_pattern(index)
        control_sentinel = cpu_sentinel(index)
        owner_actual = control_pattern if cpu_owner_pass.get(index, False) else control_sentinel
        cpu_actual = owner_actual
        if cpu_alias_diverges:
            cpu_actual = control_sentinel if owner_actual == control_pattern else control_pattern
        reset_cpu_ok = cpu_reset_secondary_pass.get(index, False)
        cpu_reset = control_sentinel if reset_cpu_ok else control_pattern
        reset_cpu_mismatches = 0 if reset_cpu_ok else 16
        cpu_mask = ((1 if owner_actual == control_pattern else 0) |
                    (2 if cpu_actual == control_pattern else 0) | 4 |
                    (8 if reset_cpu_ok else 0))
        kernel += prefix + (
            "stage=cpu_write_control executor=%s owner=%s pattern=%08x sentinel=%08x "
            "cpu_actual=%08x cpu_match=%d owner_actual=%08x owner_match=%d "
            "guard_changed=0 source_changed=0 reset_owner_mismatches=0 "
            "cpu_reset=%08x reset_cpu_mismatches=%d cpu_control_mask=%x "
            "owner_gpu_readback_primary=1 cpu_observation_secondary=1 "
            "ordering=iowrite32_ioread32_flush after_peer_results=1 "
            "peer_payload_relay=0 control_only=1\n" %
            (item["executor"], item["owner"], control_pattern, control_sentinel,
             cpu_actual, int(cpu_actual == control_pattern), owner_actual,
             int(owner_actual == control_pattern), cpu_reset,
             reset_cpu_mismatches, cpu_mask)
        )
        kernel += prefix + (
            "stage=mapping_stability physical=%x iova_first_translation=%x "
            "iova_last_translation=%x unchanged=1 target_mapping_live=1\n" %
            (item["physical"], item["physical"], item["physical"] + 4095)
        )
        kernel += prefix + (
            "stage=return operation=1 status=0 flags=df alias_mask=f host_mask=2d "
            "peer_mask=%x completed_mask=3f cpu_control_mask=%x pending=0 dma_unmapped=1 "
            "direction=DMA_FROM_DEVICE last_phase=mapping_stability\n" %
            (mask, cpu_mask)
        )
        raw += (
            "IOVA_WRITE_IOCTL index=%d request=%d rv=0 errno=0 status=0 flags=df "
            "domain=3 alias_mask=f host_mask=2d peer_mask=%x completed_mask=3f "
            "cpu_control_mask=%x bar1_phys=%x bar1_iova=%x bar1_start=%x pte_level=1 "
            "inputs_unchanged=1\n" %
            (index, item["request"], mask, cpu_mask, item["physical"], item["iova"],
             item["bar_start"])
        )

    raw += (
        "IOVA_WRITE_END protocol_complete=1 p2p_solution_claimed=0\n"
        "NATIVE_TEST_RC=0\nIOVA_DMAR_AFTER_BEGIN\nIOVA_DMAR_AFTER_END\n"
        "IOVA_DATA_DISKS_UNMOUNTED\n"
        "rootfs / rootfs rw 0 0\n"
        "proc /proc proc rw 0 0\n"
        "sysfs /sys sysfs rw 0 0\n"
        "devtmpfs /dev devtmpfs rw 0 0\n"
        "tmpfs /run tmpfs rw 0 0\n"
        "probe-esp /mnt/esp vfat rw 0 0\n"
        "PROBE_COMPLETED\nSCRIPT_RC=0\n"
    )
    return raw, kernel


class Validation(unittest.TestCase):
    def assert_incomplete(self, raw, kernel):
        result = validate_log(raw, CCFG, kernel)
        self.assertFalse(result["protocol_complete"], result)
        self.assertFalse(result["P2P_solution_claimed"])

    def test_zero_of_four_is_complete_hardware_result_not_solution(self):
        raw, kernel = fixture()
        result = validate_log(raw, CCFG, kernel)
        self.assertTrue(result["protocol_complete"], result)
        self.assertEqual(result["status"],
                         "complete_native_iova_private_vram_write_with_cpu_control")
        self.assertEqual(result["host_controls_passed"], 8)
        self.assertEqual(result["peer_writes_attempted"], 4)
        self.assertEqual(result["peer_writes_passed"], 0)
        self.assertEqual([item["operations_completed"] for item in result["executors"]],
                         [6, 6])
        self.assertEqual([item["host_controls_passed"] for item in result["executors"]],
                         [4, 4])
        self.assertTrue(all(item["dma_mapping_unmapped"] for item in result["executors"]))
        self.assertFalse(result["P2P_solution_claimed"])
        self.assertFalse(result["general_P2P_proven"])
        self.assertEqual(result["cpu_bar1_controls_attempted"], 2)
        self.assertEqual(result["cpu_bar1_controls_passed"], 2)
        self.assertFalse(result["cpu_bar1_control_is_p2p"])

    def test_zero_of_two_cpu_controls_is_complete_negative_not_p2p(self):
        raw, kernel = fixture(cpu_owner_pass={1: False, 0: False})
        result = validate_log(raw, CCFG, kernel)
        self.assertTrue(result["protocol_complete"], result)
        self.assertEqual(result["cpu_bar1_controls_passed"], 0)
        self.assertEqual([item["cpu_bar1_control"]["mask"] for item in
                          result["executors"]], [0xc, 0xc])
        self.assertFalse(result["cpu_bar1_control_is_p2p"])

    def test_secondary_cpu_control_observation_does_not_override_owner(self):
        raw, kernel = fixture(cpu_alias_diverges=True)
        result = validate_log(raw, CCFG, kernel)
        self.assertTrue(result["protocol_complete"], result)
        self.assertEqual(result["cpu_bar1_controls_passed"], 2)
        self.assertTrue(all(not item["cpu_bar1_control"]["cpu_observation_matched"]
                            for item in result["executors"]))

    def test_one_of_two_cpu_controls_is_counted_separately(self):
        raw, kernel = fixture(cpu_owner_pass={1: True, 0: False})
        result = validate_log(raw, CCFG, kernel)
        self.assertTrue(result["protocol_complete"], result)
        self.assertEqual(result["cpu_bar1_controls_passed"], 1)
        self.assertEqual([item["cpu_bar1_control"]["mask"] for item in
                          result["executors"]], [0xf, 0xc])

    def test_secondary_cpu_reset_observation_is_not_a_gate(self):
        raw, kernel = fixture(cpu_reset_secondary_pass={1: False, 0: False})
        result = validate_log(raw, CCFG, kernel)
        self.assertTrue(result["protocol_complete"], result)
        self.assertEqual(result["cpu_bar1_controls_passed"], 2)
        self.assertEqual([item["cpu_bar1_control"]["mask"] for item in
                          result["executors"]], [0x7, 0x7])

    def test_four_of_four_is_scoped_evidence_not_general_p2p(self):
        raw, kernel = fixture({1: 3, 0: 3})
        result = validate_log(raw, CCFG, kernel)
        self.assertTrue(result["protocol_complete"], result)
        self.assertEqual(result["peer_writes_passed"], 4)
        self.assertIn("scoped evidence", result["scope"])
        self.assertFalse(result["P2P_solution_claimed"])
        self.assertFalse(result["general_P2P_proven"])

    def test_partial_primary_results_are_counted_per_executor(self):
        raw, kernel = fixture({1: 1, 0: 2})
        result = validate_log(raw, CCFG, kernel)
        self.assertTrue(result["protocol_complete"], result)
        self.assertEqual(result["peer_writes_passed"], 2)
        self.assertEqual([item["peer_pass_mask"] for item in result["executors"]], [1, 2])

    def test_secondary_cpu_alias_does_not_override_owner_gpu_readback(self):
        raw, kernel = fixture({1: 3, 0: 3}, alias_diverges=True)
        result = validate_log(raw, CCFG, kernel)
        self.assertTrue(result["protocol_complete"], result)
        self.assertEqual(result["peer_writes_passed"], 4)
        self.assertEqual(len(result["peer_alias_observations"]), 4)
        self.assertTrue(all(not row["matches_expected"] for row in
                            result["peer_alias_observations"]))
        self.assertTrue(all(row["guard_changes"] == 3 for row in
                            result["peer_alias_observations"]))

    def test_raw_protocol_rejections(self):
        raw, kernel = fixture()
        mutations = [
            ("script rc", raw.replace("SCRIPT_RC=0", "SCRIPT_RC=20", 1)),
            ("native rc", raw.replace("NATIVE_TEST_RC=0", "NATIVE_TEST_RC=20", 1)),
            ("end", raw.replace("IOVA_WRITE_END protocol_complete=1",
                                "IOVA_WRITE_END protocol_complete=0", 1)),
            ("parameter", raw.replace("IOVA_WRITE_PARAMETER=Y", "IOVA_WRITE_PARAMETER=N", 1)),
            ("direction marker", raw.replace("dma_direction=DMA_FROM_DEVICE",
                                             "dma_direction=DMA_TO_DEVICE", 1)),
            ("owner primary marker", raw.replace("owner_gpu_readback_primary=1",
                                                 "owner_gpu_readback_primary=0", 1)),
            ("ordinary peer", raw.replace("ordinary_peer_access=0",
                                          "ordinary_peer_access=1", 1)),
            ("peer mapping", raw.replace("peer_mapping=0", "peer_mapping=1", 1)),
            ("GPU order", raw.replace("IOVA_WRITE_GPU index=0", "IOVA_WRITE_GPU index=1", 1)),
            ("IOCTL order", raw.replace("index=1 request=201", "index=0 request=201", 1)),
            ("client flags", raw.replace("status=0 flags=df", "status=0 flags=5f", 1)),
            ("client alias", raw.replace("domain=3 alias_mask=f", "domain=3 alias_mask=7", 1)),
            ("client input", raw.replace("inputs_unchanged=1", "inputs_unchanged=0", 1)),
            ("watchdog", raw + "WATCHDOG_REBOOT\n"),
            ("parked", raw + "IOVA_WRITE_PARKED completion_uncertain=1\n"),
            ("data mount", raw + "probe-data /mnt/private-data ext4 rw 0 0\n"),
            ("bad ESP type", raw.replace("/mnt/esp vfat", "/mnt/esp ext4", 1)),
        ]
        for name, changed in mutations:
            with self.subTest(name=name):
                self.assertNotEqual(changed, raw)
                self.assert_incomplete(changed, kernel)

    def test_mapping_alias_operation_and_cleanup_rejections(self):
        raw, kernel = fixture()
        mutations = [
            ("translation disabled", "translation_enabled=1", "translation_enabled=0"),
            ("GSTS disabled", "gsts=c7000000", "gsts=47000000"),
            ("protected region", "pmen=00000000", "pmen=80000001"),
            ("domain", "domain_type=3", "domain_type=4"),
            ("DMA direction", "direction=DMA_FROM_DEVICE", "direction=DMA_TO_DEVICE"),
            ("private target", "private_target=1", "private_target=0"),
            ("ordinary mapping", "ordinary_peer_mapping=0", "ordinary_peer_mapping=1"),
            ("BAR index", "bar_index=1", "bar_index=0"),
            ("PTE level", "cpu_pte_level=1", "cpu_pte_level=0"),
            ("resource flags", "resource_flags=2200", "resource_flags=200"),
            ("first endpoint", "translated_first=62001000", "translated_first=62002000"),
            ("last endpoint", "translated_last=62001fff", "translated_last=62001ffe"),
            ("untranslated IOVA", "iova=fe100000", "iova=62001000"),
            ("alias words", "alias_words=16", "alias_words=15"),
            ("alias owner", "owner_a_mismatches=0", "owner_a_mismatches=1"),
            ("alias CPU", "cpu_b_mismatches=0", "cpu_b_mismatches=1"),
            ("alias reset", "owner_reset_mismatches=0", "owner_reset_mismatches=1"),
            ("alias mask", "alias_mask=f", "alias_mask=7"),
            ("sequence", "stage=result seq=5", "stage=result seq=4"),
            ("operation kind", "kind=host_ram", "kind=peer_bar1"),
            ("destination", "destination_iova=f0100000", "destination_iova=f0101000"),
            ("RAM control", "expected=7bab5792 actual=7bab5792",
             "expected=7bab5792 actual=00000000"),
            ("primary guard", "guard_changed=0", "guard_changed=1"),
            ("source", "source_changed=0", "source_changed=1"),
            ("owner readback", "owner_gpu_readback=1", "owner_gpu_readback=0"),
            ("host relay", "host_relay=0", "host_relay=1"),
            ("P2P channel", "p2p_channel=0", "p2p_channel=1"),
            ("engine", "class=c7b5", "class=c6b5"),
            ("mapping changed", "unchanged=1", "unchanged=0"),
            ("mapping dead", "target_mapping_live=1", "target_mapping_live=0"),
            ("stability endpoint", "iova_last_translation=62001fff",
             "iova_last_translation=62001ffe"),
            ("CPU control ordering", "ordering=iowrite32_ioread32_flush",
             "ordering=mmiowb_only"),
            ("CPU control before peer", "after_peer_results=1",
             "after_peer_results=0"),
            ("CPU control reordered", "stage=cpu_write_control", "stage=cpu_write_control_late"),
            ("CPU relay claim", "peer_payload_relay=0", "peer_payload_relay=1"),
            ("CPU control reset", "reset_owner_mismatches=0",
             "reset_owner_mismatches=1"),
            ("CPU control mask", "cpu_control_mask=f", "cpu_control_mask=7"),
            ("return flags", "stage=return operation=1 status=0 flags=df",
             "stage=return operation=1 status=0 flags=5f"),
            ("host mask", "host_mask=2d", "host_mask=0"),
            ("completed", "completed_mask=3f", "completed_mask=1f"),
            ("pending", "pending=0", "pending=1"),
            ("not unmapped", "dma_unmapped=1", "dma_unmapped=0"),
            ("cleanup direction", "direction=DMA_FROM_DEVICE last_phase=mapping_stability",
             "direction=DMA_TO_DEVICE last_phase=mapping_stability"),
            ("last phase", "last_phase=mapping_stability", "last_phase=writes"),
        ]
        for name, old, new in mutations:
            changed = kernel.replace(old, new, 1)
            with self.subTest(name=name):
                self.assertNotEqual(changed, kernel, "fixture lacks mutation: " + name)
                self.assert_incomplete(raw, changed)

    def test_kernel_faults_and_retention_are_rejected(self):
        raw, kernel = fixture()
        mutations = [
            kernel + "NVRM: Xid 79\n",
            kernel + "DMAR: fault event\n",
            kernel + "DMA Write NO_PASID\n",
            kernel + "CASKIOVAWRITE request=201 stage=retained pending=1\n",
        ]
        for changed in mutations:
            with self.subTest(tail=changed[-80:]):
                self.assert_incomplete(raw, changed)


if __name__ == "__main__":
    unittest.main()
