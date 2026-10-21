#!/usr/bin/env python3
"""Join the unchanged 24-case protocol log to independently checked payloads.

Qualification means that the diagnostic protocol, its recorded CUPTI coverage,
and all captured destination bytes agree. It does not establish a physical
direct peer route, rederive CUPTI correlations, or identify a failing component.
Use audit_records(text, analyze_payloads.analyze_directory(directory)) to reuse
an already computed in-memory payload report without classifying bytes twice.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

import analyze_payloads as payloads


ValidationError = payloads.ValidationError
TOTAL_BYTES = 8 * (4 + 65536 + 1048576)
MAX_LOG_BYTES = 64 * 1024 * 1024


def expected_cases() -> list[dict[str, Any]]:
    result = []
    for mode in ("PUSH", "PULL"):
        for source in (0, 1):
            for size in (4, 65536, 1048576):
                for engine in (("SM", "CE_REQUEST") if mode == "PUSH" else ("CE_REQUEST", "SM")):
                    result.append({
                        "case_id": len(result) + 1, "mode": mode, "engine": engine,
                        "source": source, "destination": 1 - source,
                        "executor": source if mode == "PUSH" else 1 - source,
                        "bytes": size,
                        "seed": f"{0x6b8b4567 ^ size ^ (0x13579bdf * (source + 1)):08x}",
                    })
    return result


def ensure(condition: bool, reason: str) -> None:
    if not condition:
        raise ValidationError(reason)


def _records(lines: list[str], prefix: str) -> list[dict[str, str | int]]:
    result = []
    for line_number, line in enumerate(lines, 1):
        if not line.startswith(prefix + " "):
            continue
        record: dict[str, str | int] = {"line": line_number}
        for token in line[len(prefix) + 1:].split():
            ensure("=" in token, f"{prefix}: malformed field on line {line_number}")
            key, value = token.split("=", 1)
            ensure(key not in record, f"{prefix}: duplicate field {key}")
            record[key] = value
        result.append(record)
    return result


def _single(records: list[dict[str, Any]], label: str) -> dict[str, Any]:
    ensure(len(records) == 1, f"{label}: expected exactly one record")
    return records[0]


def _integer(record: dict[str, Any], key: str) -> int:
    ensure(key in record and isinstance(record[key], str) and re.fullmatch(r"[0-9]+", record[key]) is not None,
           f"missing or invalid integer field {key}")
    return int(record[key])


def _equal(record: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    for key, value in expected.items():
        ensure(record.get(key) == str(value), f"{label}: {key} differs from the required protocol/payload value")


def _ordered_cases(lines: list[str], prefix: str) -> list[dict[str, Any]]:
    records = _records(lines, prefix)
    ensure(len(records) == 24, f"{prefix}: expected 24 records")
    ensure([_integer(record, "id") for record in records] == list(range(1, 25)),
           f"{prefix}: IDs must be unique and ordered 1 through 24")
    return records


def _nullable_word(mismatch: dict[str, Any] | None) -> str:
    return "null" if mismatch is None else str(mismatch["word_index"])


def audit_records(log_text: str, payload_report: dict[str, Any]) -> dict[str, Any]:
    """Audit a log against a report freshly produced by analyze_payloads.

    This is an in-memory composition API, not a mechanism to authenticate an
    arbitrary saved report. The CLI always computes the payload report itself.
    """
    lines = log_text.splitlines()
    ensure(not any(line.startswith(("CE_ABORT ", "CUDA_ERROR ", "DRIVER_ERROR ", "CUPTI_ERROR ", "FATAL ")) for line in lines),
           "runtime error record present")
    case_records = _ordered_cases(lines, "CE_CASE")
    data_records = _ordered_cases(lines, "CE_DATA_RESULT")
    capture_records = _ordered_cases(lines, "PAYLOAD_CAPTURE")
    executor_records = _ordered_cases(lines, "CE_EXECUTOR")
    begin_records = _ordered_cases(lines, "CUPTI_CASE_BEGIN")
    end_records = _ordered_cases(lines, "CUPTI_CASE_END")
    trace_records = _ordered_cases(lines, "CUPTI_CASE_RESULT")
    final = _single(_records(lines, "CE_PROGRAM_END"), "CE_PROGRAM_END")
    summary = _single(_records(lines, "CUPTI_SUMMARY"), "CUPTI_SUMMARY")
    full = _records(lines, "FULL_COMPARE")
    ensure(len(full) == 72, "FULL_COMPARE: expected 48 initialization and 24 payload comparisons")
    comparisons: dict[tuple[int, str], dict[str, Any]] = {}
    for record in full:
        key = (_integer(record, "iteration"), record.get("stage"))
        ensure(key not in comparisons, "duplicate FULL_COMPARE stage/case")
        ensure(key[0] in range(1, 25) and key[1] in ("source_initialized", "destination_poisoned", "peer_payload"),
               "unexpected FULL_COMPARE stage/case")
        comparisons[key] = record
    ensure(payload_report.get("analyzer") == "payload-diagnostics-offline-v1" and payload_report.get("case_count") == 24,
           "expected a complete 24-case payload analysis")
    analyzed = payload_report.get("cases", [])
    ensure([case.get("case_id") for case in analyzed] == list(range(1, 25)), "payload IDs must be ordered 1 through 24")
    ensure(sum(case.get("bytes", 0) for case in analyzed) == TOTAL_BYTES, "captured byte total differs from 8,912,928")
    cupti_devices: dict[int, int] = {}
    for expected, begin in zip(expected_cases(), begin_records):
        for key, device in (("source_device", expected["source"]), ("target_device", expected["destination"])):
            identifier = _integer(begin, key)
            ensure(device not in cupti_devices or cupti_devices[device] == identifier, "inconsistent CUPTI device identity")
            cupti_devices[device] = identifier
    ensure(len(set(cupti_devices.values())) == 2, "CUPTI devices must be distinct")

    failures = 0
    addresses: dict[tuple[str, int], tuple[str, str]] = {}
    for expected, analyzed_case, case, data, capture, executor, begin, end, trace in zip(
        expected_cases(), analyzed, case_records, data_records, capture_records,
        executor_records, begin_records, end_records, trace_records,
    ):
        cid = expected["case_id"]
        label = f"case {cid}"
        ensure(analyzed_case.get("metadata_counts_verified") is True, f"{label}: payload counts were not verified")
        for key, value in expected.items():
            ensure(analyzed_case.get(key) == value, f"{label}: payload {key} differs from protocol")
        for key in ("observed_sha256", "metadata_sha256"):
            ensure(isinstance(analyzed_case.get(key), str) and re.fullmatch(r"[0-9a-f]{64}", analyzed_case[key]) is not None,
                   f"{label}: missing payload/sidecar SHA256")
        common = {"engine": expected["engine"], "mode": expected["mode"], "executor": expected["executor"]}
        transfer = common | {"s": expected["source"], "d": expected["destination"], "bytes": expected["bytes"]}
        _equal(case, transfer | {"seed": expected["seed"], "allocations_unchanged": 1}, label)
        _equal(data, transfer | {"checked_words": expected["bytes"] // 4, "direct_route_proven": 0}, label)
        _equal(begin, transfer | {"device": cupti_devices[expected["executor"]]}, label)
        _equal(trace, common | {"metadata_valid": 1, "coverage_complete": 1, "host_copies": 0,
                              "unattributed": 0, "direct_route_proven": 0}, label)
        ensure(all(isinstance(case.get(key), str) and re.fullmatch(r"[0-9a-fA-F]+", case[key]) for key in ("src", "dst")),
               f"{label}: missing virtual addresses")
        ensure((begin.get("src"), begin.get("dst")) == (case["src"], case["dst"]), f"{label}: CUPTI addresses differ")
        allocation_key = (expected["mode"], expected["source"])
        pair = (case["src"], case["dst"])
        ensure(allocation_key not in addresses or addresses[allocation_key] == pair, f"{label}: allocations changed within a mode/direction")
        addresses[allocation_key] = pair
        ensure(0 < _integer(begin, "timestamp") <= _integer(end, "timestamp"), f"{label}: invalid CUPTI timestamps")
        _equal(executor, {"device": expected["executor"], "valid": 1}, label)
        ensure(executor.get("current") is not None and executor.get("current") == executor.get("stream_context")
               and executor.get("stream") is not None and executor.get("stream") == begin.get("stream"), f"{label}: executor context/stream differs")
        counts = analyzed_case["counts"]
        mismatches = counts["sentinel_match_words"] + counts["other_words"]
        valid = int(mismatches == 0)
        failures += not valid
        _equal(data, {"mismatches": mismatches, "valid": valid}, label)
        _equal(capture, counts | {
            "first_mismatch_word": _nullable_word(analyzed_case["first_mismatch"]),
            "last_mismatch_word": _nullable_word(analyzed_case["last_mismatch"]),
            "observed_file": f"case-{cid:03d}.observed.u32le", "complete": 1,
        }, label)
        ensure(analyzed_case.get("observed_file") == f"case-{cid:03d}.observed.u32le"
               and analyzed_case.get("metadata_file") == f"case-{cid:03d}.json", f"{label}: payload filenames differ")
        initialization = []
        for stage, owner in (("source_initialized", expected["source"]), ("destination_poisoned", expected["destination"])):
            record = comparisons[(cid, stage)]
            _equal(record, {"owner": owner, "s": expected["source"], "d": expected["destination"],
                            "bytes": expected["bytes"], "checked_words": expected["bytes"] // 4,
                            "mismatches": 0, "valid": 1}, label)
            initialization.append(record)
        peer = comparisons[(cid, "peer_payload")]
        _equal(peer, {"owner": expected["destination"], "s": expected["source"], "d": expected["destination"],
                      "bytes": expected["bytes"], "checked_words": expected["bytes"] // 4,
                      "mismatches": mismatches, "valid": valid}, label)
        if mismatches:
            first = analyzed_case["first_mismatch"]
            _equal(peer, {"first_index": first["word_index"], "first_got": first["observed"], "first_expected": first["expected"]}, label)
        else:
            ensure(not any(key in peer for key in ("first_index", "first_got", "first_expected")), f"{label}: mismatch fields in a passing comparison")
        sequence = [case, *initialization, executor, begin, end, peer, capture, data]
        ensure(all(left["line"] < right["line"] for left, right in zip(sequence, sequence[1:])), f"{label}: invalid initialization/transfer/capture ordering")
        if cid < 24:
            ensure(data["line"] < case_records[cid]["line"], f"{label}: overlapping case records")
        ce = expected["engine"] == "CE_REQUEST"
        if ce:
            ensure(_integer(trace, "copies") >= 1, f"{label}: no recorded CE copy")
            _equal(trace, {"kernels": 0, "copy_bytes": expected["bytes"], "d2d_entries": 1,
                           "d2d_exits": 1, "d2d_driver": 1, "ce_observed": 1}, label)
        else:
            _equal(trace, {"copies": 0, "kernels": 1, "copy_bytes": 0, "d2d_entries": 0,
                           "d2d_exits": 0, "d2d_driver": 0, "ce_observed": 0}, label)
        ensure(data_records[-1]["line"] < trace["line"] < summary["line"], f"{label}: trace classification is out of order")

    _equal(summary, {"trace_complete": 1, "cases": 24, "ce_cases": 12, "ce_observed": 12,
                     "sm_observed": 12, "dropped": 0, "errors": 0, "direct_route_proven": 0}, "CUPTI_SUMMARY")
    expected_rc = 5 if failures else 0
    _equal(final, {"protocol_complete": 1, "comparisons": 24, "failures": failures, "trace_complete": 1,
                   "ce_cases": 12, "ce_observed": 12, "sm_observed": 12, "dropped": 0,
                   "trace_errors": 0, "direct_route_proven": 0, "rc": expected_rc}, "CE_PROGRAM_END")
    ensure(summary["line"] < final["line"], "final program marker precedes trace summary")
    wrapper_lines = []
    for marker in ("NATIVE_TEST_RC", "SCRIPT_RC"):
        found = [(number, line.split("=", 1)[1]) for number, line in enumerate(lines, 1) if line.startswith(marker + "=")]
        ensure(len(found) == 1 and found[0][1] == str(expected_rc), f"{marker}: missing, duplicate, or inconsistent return code")
        wrapper_lines.append(found[0][0])
    completed = [number for number, line in enumerate(lines, 1) if line == "PROBE_COMPLETED"]
    ensure(len(completed) == 1 and final["line"] < wrapper_lines[0] < completed[0] < wrapper_lines[1],
           "missing or out-of-order PROBE_COMPLETED/wrapper markers")
    return {
        "schema_version": 1,
        "validator": "payload-protocol-validator-v1",
        "status": "COMPLETE_DIAGNOSTIC_EVIDENCE",
        "diagnostic_run_qualified": True,
        "qualification_scope": "Protocol, initialization, recorded CUPTI coverage, and captured payload consistency; not a physical-path certification.",
        "comparisons": 24, "passing_cases": 24 - failures, "failing_cases": failures,
        "initialization_checks": 48, "ce_observed": 12, "sm_observed": 12,
        "trace_complete": True, "dropped": 0, "trace_errors": 0, "program_rc": expected_rc,
        "all_payloads_match": failures == 0, "direct_route_proven": False, "p2p_fix_established": False,
        "payload_bytes": TOTAL_BYTES, "payload_mib": TOTAL_BYTES / (1024 * 1024),
        "evidence": {
            "path_note": "Logical relative labels only: result.log is the supplied log; payloads/ is the supplied payload directory.",
            "result_log": "result.log",
            "payloads": [{"case_id": case["case_id"], "raw": "payloads/" + case["observed_file"],
                          "raw_sha256": case["observed_sha256"], "metadata": "payloads/" + case["metadata_file"],
                          "metadata_sha256": case["metadata_sha256"], "bytes": case["bytes"]} for case in analyzed],
        },
        "limitations": list(payload_report.get("limitations", [])) + [
            "Recorded CUPTI per-case coverage is cross-checked here; callback/correlation reconstruction is a separate audit.",
            "CUPTI does not expose final hardware transfer descriptors or exclude every possible internal staging path.",
            "PUSH and PULL still use separate allocations and virtual mappings; this is not a same-allocation A/B test.",
            "A complete diagnostic run, including 24 passing payloads if observed, is not by itself a certified P2P fix.",
        ],
        "cases": analyzed,
    }


def validate_run(log_path: Path, payload_directory: Path) -> dict[str, Any]:
    log_path = Path(log_path)
    ensure(log_path.is_file() and not log_path.is_symlink(), "result log must be a regular, non-symlink file")
    ensure(log_path.stat().st_size <= MAX_LOG_BYTES, "result log exceeds 64 MiB")
    with log_path.open("rb") as handle:
        raw = handle.read(MAX_LOG_BYTES + 1)
    ensure(len(raw) <= MAX_LOG_BYTES, "result log exceeds 64 MiB")
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise ValidationError("result log must be UTF-8") from exc
    report = audit_records(text, payloads.analyze_directory(payload_directory))
    report["evidence"]["result_log_sha256"] = hashlib.sha256(raw).hexdigest()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("payload_directory", type=Path)
    parser.add_argument("--output", type=Path, help="create a new JSON report; never overwrite an existing file")
    args = parser.parse_args(argv)
    try:
        report = validate_run(args.log, args.payload_directory)
        encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output is None:
            sys.stdout.write(encoded)
        else:
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(encoded)
            print(f"Created {args.output}")
    except (ValidationError, OSError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
