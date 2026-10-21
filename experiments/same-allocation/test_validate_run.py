"""Synthetic CPU fixtures only: none of these tests is hardware evidence."""

from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

_SPEC = importlib.util.spec_from_file_location("same_allocation_validator", Path(__file__).with_name("validate_run.py"))
assert _SPEC and _SPEC.loader
validator = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(validator)


def record(prefix, **values):
    return prefix + " " + " ".join(f"{key}={value}" for key, value in values.items())


def fixture(all_pass=False):
    lines, analyses, deferred_callbacks, operations, classified = [], [], [], [], []
    addresses = (0x10000000, 0x20000000)
    handles = (0xabc000, 0xdef000)

    def identity(device):
        return record("CE_GPU", index=device, bdf=("0000:01:00.0", "0000:06:00.0")[device],
                      uuid=f"{device + 1:032x}", name="Synthetic GPU fixture", valid=1)

    def access(stage, owner):
        for device in (0, 1):
            lines.append(record("CE_ACCESS", stage=stage, owner=owner, mode="SHARED", role="shared", device=device,
                                va=f"{addresses[owner]:x}", last_va=f"{addresses[owner] + validator.ALLOCATION_BYTES - 1:x}",
                                first=3, last=3, expected=3, allocation_type=1, location_type=1, location_id=owner, valid=1))

    lines.append(record("SA_PROTOCOL", name="same-allocation-bracket-v1", allocations=2, comparisons=36, groups=12))
    lines.append(record("CUPTI_READY", version=24, memcpy_record=5, ptop_record=4, kernel_record=9))
    lines += [identity(0), identity(1)]
    for owner in (0, 1):
        lines.append(record("CE_ALLOCATION", nonce=f"00000000-0000-0000-0000-{owner+1:012x}", owner=owner, mode="SHARED",
                            role="shared", va=f"{addresses[owner]:x}", handle=f"{handles[owner]:x}",
                            allocation_bytes=validator.ALLOCATION_BYTES, granularity=2097152))
        access("created", owner)
    failures = 0
    for spec in validator.expected_cases():
        cid, size, executor = spec["case_id"], spec["bytes"], spec["executor"]
        passing = all_pass or (spec["mode"] == "PUSH" and spec["source"] == 1)
        failures += not passing
        if spec["step"] == "PUSH_BEFORE":
            lines.append(record("SA_GROUP_BEGIN", group=spec["group"], executor=executor, engine=spec["engine"],
                                bytes=size, base_seed=spec["base_seed"], first_case=cid))
        lines += [identity(0), identity(1)]
        for owner in (0, 1):
            access("before_case", owner)
        lines.append(record("SA_CASE", id=cid, group=spec["group"], step=spec["step"], buffer0=f"{addresses[0]:x}",
                            buffer1=f"{addresses[1]:x}", handle0=f"{handles[0]:x}", handle1=f"{handles[1]:x}"))
        common = {"id": cid, "engine": spec["engine"], "mode": spec["mode"], "executor": executor}
        transfer = common | {"s": spec["source"], "d": spec["destination"], "bytes": size}
        address = {"src": f"{addresses[spec['source']]:x}", "dst": f"{addresses[spec['destination']]:x}"}
        lines.append(record("CE_CASE", **transfer, seed=spec["seed"], **address, allocations_unchanged=1))
        words = size // 4
        base = {"s": spec["source"], "d": spec["destination"], "bytes": size, "iteration": cid, "checked_words": words}
        lines.append(record("FULL_COMPARE", stage="source_initialized", owner=spec["source"], **base, mismatches=0, valid=1))
        lines.append(record("FULL_COMPARE", stage="destination_poisoned", owner=spec["destination"], **base, mismatches=0, valid=1))
        context = 10 + executor
        stream = f"0x{0x3000 + executor:x}"
        lines.append(record("CE_EXECUTOR", id=cid, device=executor, current=f"0x{0x2000 + executor:x}",
                            stream_context=f"0x{0x2000 + executor:x}", stream=stream, valid=1))
        lines.append(record("CUPTI_CASE_BEGIN", **transfer, device=executor, source_device=spec["source"], target_device=spec["destination"],
                            context=context, stream_id=20 + executor, stream=stream, **address, timestamp=cid * 100))
        ce = spec["engine"] == "CE_REQUEST"
        corr = 1000 + cid
        callback = {"case": cid, "corr": corr, "cbid": 281 if ce else 678, "context": context, "is_d2d": int(ce),
                    "src": address["src"] if ce else "0", "dst": address["dst"] if ce else "0", "bytes": size if ce else 0,
                    "stream": stream if ce else "(nil)"}
        deferred_callbacks.append(record("CUPTI_CALLBACK", **callback, site=0, result=-1))
        deferred_callbacks.append(record("CUPTI_CALLBACK", **callback, site=1, result=0))
        lines.append(record("CUPTI_CASE_END", id=cid, timestamp=cid * 100 + 10))
        seed = int(spec["seed"], 16)

        def mismatch(index):
            value = validator.payloads.word_pattern(index, seed)
            observed = value ^ 0xffffffff if spec["mode"] == "PUSH" else 0xffffffff
            return {"word_index": index, "byte_offset": 4 * index, "expected": f"{value:08x}",
                    "observed": f"{observed:08x}", "sentinel": f"{value ^ 0xffffffff:08x}"}

        first, last = (None, None) if passing else (mismatch(0), mismatch(words - 1))
        counts = {"correct_words": words if passing else 0,
                  "sentinel_match_words": words if not passing and spec["mode"] == "PUSH" else 0,
                  "other_words": words if not passing and spec["mode"] == "PULL" else 0}
        first_fields = {} if passing else {"first_index": 0, "first_got": first["observed"], "first_expected": first["expected"]}
        lines.append(record("FULL_COMPARE", stage="peer_payload", owner=spec["destination"], **base,
                            mismatches=0 if passing else words, valid=int(passing), **first_fields))
        lines.append(record("PAYLOAD_CAPTURE", id=cid, **counts, first_mismatch_word="null" if passing else 0,
                            last_mismatch_word="null" if passing else words - 1, observed_file=f"case-{cid:03d}.observed.u32le", complete=1))
        lines.append(record("CE_DATA_RESULT", **transfer, checked_words=words, mismatches=0 if passing else words,
                            valid=int(passing), direct_route_proven=0))
        for owner in (0, 1):
            access("after_case", owner)
        if spec["step"] == "PUSH_AFTER":
            lines.append(record("SA_GROUP_END", group=spec["group"], last_case=cid))
        analyses.append({key: spec[key] for key in ("case_id", "mode", "engine", "source", "destination", "executor", "bytes", "seed")} | {
            "metadata_counts_verified": True, "observed_file": f"case-{cid:03d}.observed.u32le", "metadata_file": f"case-{cid:03d}.json",
            "observed_sha256": "a" * 64, "metadata_sha256": "b" * 64, "counts": counts, "first_mismatch": first, "last_mismatch": last,
            "same_allocations_across_modes": True, "direct_route_proven": False,
            "source_va": address["src"], "destination_va": address["dst"],
        })
        operation = {"case": cid, "corr": corr, "device": executor, "context": context, "stream_id": 20 + executor,
                     "channel": 1, "channel_type": 2 if ce else 1, "copy_kind": 10 if ce else 0,
                     "src_kind": 3 if ce else 0, "dst_kind": 3 if ce else 0,
                     "src_device": spec["source"], "dst_device": spec["destination"], "bytes": size if ce else 0,
                     "start": cid * 100 + 1, "end": cid * 100 + 9, "cbid": 281 if ce else 678,
                     "external": 0, "name": "none" if ce else "_Z16peer_push_kernelPKjPVjm"}
        operations.append(record("CUPTI_RECORD", kind=39, **(operation | {"external": cid})))
        operations.append(record("CUPTI_RECORD", kind=4, **operation))
        operations.append(record("CUPTI_RECORD", kind=22 if ce else 10, **operation))
        classified.append(record("CUPTI_CASE_RESULT", **common, copies=int(ce), kernels=int(not ce), copy_bytes=size if ce else 0,
                                 host_copies=0, unattributed=0, d2d_entries=int(ce), d2d_exits=int(ce), d2d_driver=int(ce),
                                 metadata_valid=1, coverage_complete=1, ce_observed=int(ce), direct_route_proven=0))
    lines.append(record("CaskLogicCE", phase="data_done", s=-1, d=-1))
    lines += deferred_callbacks + operations + classified
    lines.append(record("CUPTI_SUMMARY", trace_complete=1, cases=36, ce_cases=18, ce_observed=18, sm_observed=18, dropped=0, errors=0, direct_route_proven=0))
    for owner in (0, 1):
        lines.append(record("CaskLogicCE", phase="allocation_free_begin", s=owner, d=-1))
        lines.append(record("CaskLogicCE", phase="allocation_free_done", s=owner, d=-1))
    lines.append(record("CaskLogicCE", phase="cleanup_done", s=-1, d=-1))
    rc = 5 if failures else 0
    lines.append(record("CE_PROGRAM_END", protocol_complete=1, comparisons=36, failures=failures, trace_complete=1,
                        ce_cases=18, ce_observed=18, sm_observed=18, dropped=0, trace_errors=0, direct_route_proven=0, rc=rc))
    lines += [f"NATIVE_TEST_RC={rc}", "PROBE_COMPLETED", f"SCRIPT_RC={rc}"]
    return "\n".join(lines) + "\n", {"analyzer": "payload-diagnostics-offline-v1", "case_count": 36, "cases": analyses, "limitations": []}


class SameAllocationProtocolTests(unittest.TestCase):
    def setUp(self):
        self.log, self.report = fixture()

    def assert_invalid(self, log=None, report=None, reason=None):
        with self.assertRaisesRegex(validator.ValidationError, reason or ".*"):
            validator.audit_records(self.log if log is None else log, self.report if report is None else report)

    def test_complete_failed_run_qualifies_only_diagnostics(self):
        result = validator.audit_records(self.log, self.report)
        self.assertEqual((result["passing_cases"], result["failing_cases"]), (12, 24))
        self.assertEqual(result["payload_bytes"], 13369392)
        self.assertTrue(result["cupti_independently_reconstructed"])
        self.assertTrue(result["same_software_allocations_across_modes"])
        self.assertFalse(result["direct_route_proven"])
        self.assertFalse(result["p2p_fix_established"])

    def test_each_case_seed_is_fresh_and_group_order_is_fixed(self):
        specs = validator.expected_cases()
        self.assertEqual(len(specs), 36)
        self.assertEqual(len({item["seed"] for item in specs}), 36)
        self.assertEqual([item["step"] for item in specs[:3]], ["PUSH_BEFORE", "PULL", "PUSH_AFTER"])
        self.assertEqual([item["executor"] for item in specs], [1] * 18 + [0] * 18)
        self.assertEqual(specs[0]["base_seed"], "4d2472dd")
        self.assertEqual(specs[0]["seed"], "d3130b64")
        self.assertEqual(len({item["base_seed"] for item in specs[:3]}), 1)
        self.assertNotEqual(specs[0]["seed"], specs[1]["seed"])

    def test_all_numerical_passes_still_do_not_certify_route(self):
        log, report = fixture(all_pass=True)
        result = validator.audit_records(log, report)
        self.assertTrue(result["all_payloads_match"])
        self.assertEqual(result["program_rc"], 0)
        self.assertFalse(result["p2p_fix_established"])

    def test_swapped_or_changed_addresses_handles_and_executor_rejected(self):
        for old, new in (("buffer0=10000000 buffer1=20000000", "buffer0=20000000 buffer1=10000000"),
                         ("handle0=abc000 handle1=def000", "handle0=def000 handle1=abc000"),
                         ("src=20000000 dst=10000000", "src=10000000 dst=20000000"),
                         ("engine=CE_REQUEST mode=PUSH executor=1", "engine=CE_REQUEST mode=PUSH executor=0"),
                         ("first=3 last=3 expected=3", "first=1 last=1 expected=1"),
                         ("stream_context=0x2001", "stream_context=0x9999")):
            with self.subTest(old=old):
                self.assertIn(old, self.log)
                self.assert_invalid(self.log.replace(old, new, 1))

    def test_missing_duplicate_and_reordered_groups(self):
        lines = self.log.splitlines(True)
        for prefix in ("SA_PROTOCOL", "SA_GROUP_BEGIN", "SA_GROUP_END", "SA_CASE", "CE_CASE", "CE_ACCESS", "CE_GPU", "CE_ALLOCATION"):
            first = next(line for line in lines if line.startswith(prefix + " "))
            with self.subTest(prefix=prefix):
                self.assert_invalid(self.log.replace(first, "", 1))
                self.assert_invalid(self.log + first)
        self.assert_invalid(self.log.replace("SA_GROUP_BEGIN group=1 ", "SA_GROUP_BEGIN group=2 ", 1))
        self.assert_invalid(self.log.replace("step=PULL", "step=PUSH_AFTER", 1))
        self.assert_invalid(self.log.replace("first_case=1\n", "first_case=2\n", 1))

    def test_cupti_claims_cannot_hide_wrong_execution_or_correlation(self):
        operations = [line for line in self.log.splitlines(True) if line.startswith("CUPTI_RECORD ")]
        peer = next(line for line in operations if "kind=22 " in line)
        for changed in (peer.replace("device=1 ", "device=0 ", 1), peer.replace("context=11 ", "context=10 ", 1),
                        peer.replace("corr=1001 ", "corr=9999 ", 1), peer.replace("channel_type=2 ", "channel_type=1 ", 1),
                        peer.replace("src_kind=3 ", "src_kind=1 ", 1), peer.replace("bytes=4 ", "bytes=8 ", 1),
                        peer.replace("start=101 ", "start=99 ", 1)):
            with self.subTest(changed=changed):
                self.assert_invalid(self.log.replace(peer, changed, 1))
        callback = next(line for line in self.log.splitlines(True) if line.startswith("CUPTI_CALLBACK "))
        self.assert_invalid(self.log.replace(callback, "", 1))
        self.assert_invalid(callback + self.log.replace(callback, "", 1))
        exit_callback = next(line for line in self.log.splitlines(True) if line.startswith("CUPTI_CALLBACK ") and "site=1" in line)
        lines = self.log.splitlines(True)
        entry_index, exit_index = lines.index(callback), lines.index(exit_callback)
        lines[entry_index], lines[exit_index] = lines[exit_index], lines[entry_index]
        self.assert_invalid("".join(lines))
        self.assert_invalid(self.log.replace("external=1 ", "external=2 ", 1))
        kernel = next(line for line in operations if " kind=10 " in line)
        self.assert_invalid(self.log.replace(kernel, kernel.replace("peer_push_kernel", "unrelated_kernel"), 1))

    def test_counts_mismatch_bounds_and_sidecar_identity_are_verified(self):
        for old, new in (("correct_words=1", "correct_words=0"), ("last_mismatch_word=0", "last_mismatch_word=null"),
                         ("complete=1", "complete=0"), ("seed=d3130b64", "seed=4d2472dd"),
                         ("direct_route_proven=0", "direct_route_proven=1"), ("dropped=0", "dropped=1")):
            with self.subTest(old=old):
                self.assert_invalid(self.log.replace(old, new, 1))
        for key, value in (("source_va", "10000000"), ("destination_va", "20000000"), ("seed", "00000000"),
                           ("same_allocations_across_modes", False), ("direct_route_proven", True),
                           ("metadata_counts_verified", False), ("observed_sha256", "bad"), ("bytes", 8)):
            report = copy.deepcopy(self.report)
            report["cases"][0][key] = value
            with self.subTest(key=key):
                self.assert_invalid(report=report)
        report = copy.deepcopy(self.report)
        report["cases"][1]["last_mismatch"]["expected"] = "ffffffff"
        self.assert_invalid(report=report)

    def test_early_free_missing_initialization_and_bad_rc_fail(self):
        line = next(line for line in self.log.splitlines(True) if "phase=allocation_free_begin" in line)
        self.assert_invalid(line + self.log.replace(line, "", 1))
        line = next(line for line in self.log.splitlines(True) if "stage=source_initialized" in line)
        self.assert_invalid(self.log.replace(line, "", 1))
        self.assert_invalid(self.log.replace("NATIVE_TEST_RC=5", "NATIVE_TEST_RC=0"))
        self.assert_invalid(self.log.replace("PROBE_COMPLETED\n", ""))

    def test_cli_hash_and_exclusive_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log, output = root / "private.log", root / "result.json"
            log.write_text(self.log)
            with patch.object(validator, "analyze_payload_directory", return_value=self.report):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(validator.main([str(log), str(root), "--output", str(output)]), 0)
                saved = output.read_bytes()
                report = json.loads(saved)
                self.assertEqual(report["evidence"]["result_log_sha256"], hashlib.sha256(log.read_bytes()).hexdigest())
                self.assertNotIn(directory, saved.decode())
                with redirect_stderr(io.StringIO()):
                    self.assertEqual(validator.main([str(log), str(root), "--output", str(output)]), 2)
                self.assertEqual(saved, output.read_bytes())


class RawPayloadTests(unittest.TestCase):
    def make_payload(self, directory):
        seed = 0x12345678
        expected = [validator.payloads.word_pattern(index, seed) for index in range(16)]
        actual = expected.copy()
        actual[3] = expected[3] ^ 0xffffffff
        actual[9] = expected[1]
        raw = b"".join(struct.pack("<I", value) for value in actual)
        metadata = {"schema_version": 1, "case_id": 36, "mode": "PUSH", "engine": "SM", "source": 0, "destination": 1,
                    "executor": 0, "bytes": len(raw), "seed": f"{seed:08x}", "observed_file": "case-036.observed.u32le",
                    "pattern": validator.payloads.PATTERN, "sentinel": validator.payloads.SENTINEL, "byte_order": "little", "word_bytes": 4,
                    "source_va": "10000000", "destination_va": "20000000", "same_allocations_across_modes": True,
                    "direct_route_proven": False, "first_mismatch_word": 3, "last_mismatch_word": 9,
                    "correct_words": 14, "sentinel_match_words": 1, "other_words": 1}
        raw_path, metadata_path = Path(directory) / metadata["observed_file"], Path(directory) / "case-036.json"
        raw_path.write_bytes(raw)
        metadata_path.write_text(json.dumps(metadata))
        return raw_path, metadata_path, metadata

    def test_real_bytes_classify_first_last_and_offset_pattern(self):
        with tempfile.TemporaryDirectory() as directory:
            raw, _, _ = self.make_payload(directory)
            report = validator.analyze_payload_directory(Path(directory))
            case = report["cases"][0]
            self.assertEqual(case["first_mismatch"]["byte_offset"], 12)
            self.assertEqual(case["last_mismatch"]["byte_offset"], 36)
            self.assertEqual(case["counts"], {"correct_words": 14, "sentinel_match_words": 1, "other_words": 1})
            self.assertEqual(case["observed_sha256"], hashlib.sha256(raw.read_bytes()).hexdigest())
            self.assertEqual(case["source_va"], "10000000")
            self.assertTrue(case["same_allocations_across_modes"])

    def test_truncated_payload_and_false_capture_counts_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            raw, sidecar, metadata = self.make_payload(directory)
            saved = raw.read_bytes()
            raw.write_bytes(saved[:-4])
            with self.assertRaisesRegex(validator.ValidationError, "length"):
                validator.analyze_payload_directory(Path(directory))
            raw.write_bytes(saved)
            metadata["correct_words"], metadata["other_words"] = 15, 0
            sidecar.write_text(json.dumps(metadata))
            with self.assertRaisesRegex(validator.ValidationError, "computed"):
                validator.analyze_payload_directory(Path(directory))

    def test_last_bound_and_mapping_fields_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            _, sidecar, metadata = self.make_payload(directory)
            for key in ("last_mismatch_word", "source_va", "same_allocations_across_modes"):
                incomplete = dict(metadata)
                del incomplete[key]
                sidecar.write_text(json.dumps(incomplete))
                with self.subTest(key=key), self.assertRaises(validator.ValidationError):
                    validator.analyze_payload_directory(Path(directory))


if __name__ == "__main__":
    unittest.main()
