"""Synthetic protocol fixtures; these tests do not supply hardware evidence."""

from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import analyze_payloads
import validate_run as validator


def fixture(all_pass=False):
    lines, analyzed, trace_lines = [], [], []

    def record(name, **fields):
        return name + " " + " ".join(f"{key}={value}" for key, value in fields.items())

    for expected in validator.expected_cases():
        cid, size = expected["case_id"], expected["bytes"]
        passing = all_pass or (expected["mode"] == "PUSH" and expected["source"] == 1)
        words = size // 4
        first_value = analyze_payloads.word_pattern(0, int(expected["seed"], 16))
        first = None if passing else {"word_index": 0, "byte_offset": 0,
                                     "observed": f"{first_value ^ 0xffffffff:08x}", "expected": f"{first_value:08x}"}
        last = None if passing else {"word_index": words - 1, "byte_offset": size - 4}
        counts = {"correct_words": words if passing else 0, "sentinel_match_words": 0 if passing else words, "other_words": 0}
        analyzed.append(expected | {
            "metadata_counts_verified": True, "observed_file": f"case-{cid:03d}.observed.u32le",
            "metadata_file": f"case-{cid:03d}.json", "observed_sha256": "a" * 64, "metadata_sha256": "b" * 64,
            "counts": counts, "first_mismatch": first, "last_mismatch": last,
        })
        common = {"id": cid, "engine": expected["engine"], "mode": expected["mode"], "executor": expected["executor"]}
        transfer = common | {"s": expected["source"], "d": expected["destination"], "bytes": size}
        address = 0x100000 + (0 if expected["mode"] == "PUSH" else 0x400000) + expected["source"] * 0x200000
        addresses = {"src": f"{address:x}", "dst": f"{address + 0x100000:x}"}
        lines.append(record("CE_CASE", **transfer, seed=expected["seed"], **addresses, allocations_unchanged=1))
        base_compare = {"s": expected["source"], "d": expected["destination"], "bytes": size, "iteration": cid, "checked_words": words}
        lines.append(record("FULL_COMPARE", stage="source_initialized", owner=expected["source"], **base_compare, mismatches=0, valid=1))
        lines.append(record("FULL_COMPARE", stage="destination_poisoned", owner=expected["destination"], **base_compare, mismatches=0, valid=1))
        lines.append(record("CE_EXECUTOR", id=cid, device=expected["executor"], current="0x123", stream_context="0x123", stream="0x456", valid=1))
        lines.append(record("CUPTI_CASE_BEGIN", **transfer, device=expected["executor"], source_device=expected["source"],
                            target_device=expected["destination"], **addresses, stream="0x456", timestamp=cid * 10))
        lines.append(record("CUPTI_CASE_END", id=cid, timestamp=cid * 10 + 1))
        first_fields = {} if passing else {"first_index": 0, "first_got": first["observed"], "first_expected": first["expected"]}
        lines.append(record("FULL_COMPARE", stage="peer_payload", owner=expected["destination"], **base_compare,
                            mismatches=0 if passing else words, valid=int(passing), **first_fields))
        lines.append(record("PAYLOAD_CAPTURE", id=cid, **counts, first_mismatch_word="null" if passing else 0,
                            last_mismatch_word="null" if passing else words - 1, observed_file=f"case-{cid:03d}.observed.u32le", complete=1))
        lines.append(record("CE_DATA_RESULT", **transfer, checked_words=words, mismatches=0 if passing else words,
                            valid=int(passing), direct_route_proven=0))
        ce = expected["engine"] == "CE_REQUEST"
        trace_lines.append(record("CUPTI_CASE_RESULT", **common, copies=int(ce), kernels=int(not ce), copy_bytes=size if ce else 0,
                                  host_copies=0, unattributed=0, d2d_entries=int(ce), d2d_exits=int(ce), d2d_driver=int(ce),
                                  metadata_valid=1, coverage_complete=1, ce_observed=int(ce), direct_route_proven=0))
    lines += trace_lines
    failures, rc = (0, 0) if all_pass else (18, 5)
    lines.append(record("CUPTI_SUMMARY", trace_complete=1, cases=24, ce_cases=12, ce_observed=12, sm_observed=12, dropped=0, errors=0, direct_route_proven=0))
    lines.append(record("CE_PROGRAM_END", protocol_complete=1, comparisons=24, failures=failures, trace_complete=1,
                        ce_cases=12, ce_observed=12, sm_observed=12, dropped=0, trace_errors=0, direct_route_proven=0, rc=rc))
    lines += [f"NATIVE_TEST_RC={rc}", "PROBE_COMPLETED", f"SCRIPT_RC={rc}"]
    report = {"analyzer": "payload-diagnostics-offline-v1", "case_count": 24, "cases": analyzed, "limitations": []}
    return "\n".join(lines) + "\n", report


class CompleteRunTests(unittest.TestCase):
    def setUp(self):
        self.log, self.report = fixture()

    def test_historical_mapping_and_total_size(self):
        cases = validator.expected_cases()
        self.assertEqual(len(cases), 24)
        self.assertEqual(cases[0]["seed"], "78dcdebc")
        self.assertEqual(cases[6]["seed"], "4d2472dd")
        self.assertEqual(cases[12]["engine"], "CE_REQUEST")
        self.assertEqual(cases[13]["engine"], "SM")
        self.assertEqual(sum(case["bytes"] for case in cases), 8912928)

    def test_complete_failed_run_qualifies_diagnostics_only(self):
        result = validator.audit_records(self.log, self.report)
        self.assertEqual(result["failing_cases"], 18)
        self.assertEqual(result["passing_cases"], 6)
        self.assertTrue(result["diagnostic_run_qualified"])
        self.assertFalse(result["direct_route_proven"])
        self.assertFalse(result["p2p_fix_established"])
        self.assertEqual(result["payload_bytes"], 8912928)
        self.assertTrue(all(item["raw"].startswith("payloads/case-") for item in result["evidence"]["payloads"]))

    def test_zero_return_code_requires_all_payloads_match(self):
        log, report = fixture(all_pass=True)
        result = validator.audit_records(log, report)
        self.assertTrue(result["all_payloads_match"])
        self.assertEqual(result["program_rc"], 0)
        self.assertFalse(result["p2p_fix_established"])

    def test_missing_or_duplicate_case_records_rejected(self):
        for prefix in ("CE_CASE", "CE_DATA_RESULT", "PAYLOAD_CAPTURE", "CE_EXECUTOR", "CUPTI_CASE_BEGIN", "CUPTI_CASE_END", "CUPTI_CASE_RESULT"):
            first = next(line for line in self.log.splitlines(True) if line.startswith(prefix + " "))
            for log in (self.log.replace(first, "", 1), self.log + first):
                with self.subTest(prefix=prefix):
                    with self.assertRaises(validator.ValidationError):
                        validator.audit_records(log, self.report)

    def test_protocol_and_capture_tampering_rejected(self):
        changes = (
            ("seed=78dcdebc", "seed=00000000"),
            ("engine=SM mode=PUSH executor=0", "engine=SM mode=PUSH executor=1"),
            ("last_mismatch_word=0", "last_mismatch_word=null"),
            ("sentinel_match_words=1", "sentinel_match_words=0"),
            ("first_got=a56887da", "first_got=ffffffff"),
            ("stream_context=0x123", "stream_context=0x999"),
            ("complete=1", "complete=0"),
            ("allocations_unchanged=1", "allocations_unchanged=0"),
        )
        for old, new in changes:
            with self.subTest(old=old):
                self.assertIn(old, self.log)
                with self.assertRaises(validator.ValidationError):
                    validator.audit_records(self.log.replace(old, new, 1), self.report)

    def test_incomplete_trace_and_bad_return_codes_rejected(self):
        for old, new in (("dropped=0", "dropped=1"), ("errors=0", "errors=1"),
                         ("coverage_complete=1", "coverage_complete=0"), ("ce_observed=12", "ce_observed=11"),
                         ("NATIVE_TEST_RC=5", "NATIVE_TEST_RC=6"), ("SCRIPT_RC=5", "SCRIPT_RC=0"),
                         ("PROBE_COMPLETED\n", ""), ("failures=18", "failures=17"),
                         ("direct_route_proven=0", "direct_route_proven=1")):
            with self.subTest(old=old):
                with self.assertRaises(validator.ValidationError):
                    validator.audit_records(self.log.replace(old, new, 1), self.report)

    def test_initialization_and_capture_order_matter(self):
        lines = self.log.splitlines()
        lines[1], lines[7] = lines[7], lines[1]
        with self.assertRaisesRegex(validator.ValidationError, "ordering"):
            validator.audit_records("\n".join(lines), self.report)
        bad = self.log.replace("stage=source_initialized owner=0 s=0 d=1 bytes=4 iteration=1 checked_words=1 mismatches=0 valid=1",
                               "stage=source_initialized owner=0 s=0 d=1 bytes=4 iteration=1 checked_words=1 mismatches=1 valid=0", 1)
        with self.assertRaises(validator.ValidationError):
            validator.audit_records(bad, self.report)

    def test_payload_report_disagreement_rejected(self):
        for key, value in (("seed", "00000000"), ("source", 1), ("bytes", 8), ("case_id", 2),
                           ("metadata_counts_verified", False), ("observed_sha256", "bad"),
                           ("observed_file", "../case-001.observed.u32le")):
            with self.subTest(key=key):
                report = copy.deepcopy(self.report)
                report["cases"][0][key] = value
                with self.assertRaises(validator.ValidationError):
                    validator.audit_records(self.log, report)

    def test_log_sha_and_exclusive_cli_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / "private-result.log"
            log.write_text(self.log, encoding="utf-8")
            output = root / "report.json"
            with patch.object(validator.payloads, "analyze_directory", return_value=self.report) as mocked:
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(validator.main([str(log), str(root), "--output", str(output)]), 0)
                mocked.assert_called_once()
                saved = output.read_bytes()
                result = json.loads(saved)
                self.assertEqual(result["evidence"]["result_log_sha256"], hashlib.sha256(log.read_bytes()).hexdigest())
                self.assertNotIn(temporary, saved.decode())
                self.assertNotIn("private-result.log", saved.decode())
                with redirect_stderr(io.StringIO()):
                    self.assertEqual(validator.main([str(log), str(root), "--output", str(output)]), 2)
                self.assertEqual(output.read_bytes(), saved)


if __name__ == "__main__":
    unittest.main()
