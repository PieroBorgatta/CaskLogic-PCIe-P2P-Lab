#!/usr/bin/env python3
"""Independently audit the 36-case same-allocation bracket experiment offline.

This checks software allocation identity, access queries, freshly classified
payload bytes and raw CUPTI correlations. It does not certify hardware routing,
physical PTE identity, absence of internal staging, or a firmware/driver fix.
Numerical failures are valid diagnostic evidence when the protocol is complete.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any


_SPEC = importlib.util.spec_from_file_location(
    "same_allocation_payload_analyzer", Path(__file__).resolve().parents[1] / "payload-diagnostics" / "analyze_payloads.py")
assert _SPEC and _SPEC.loader
payloads = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(payloads)
ValidationError = payloads.ValidationError
CASE_COUNT = 36
GROUP_COUNT = 12
ALLOCATION_BYTES = 8 * 1024 * 1024
TOTAL_BYTES = 12 * (4 + 65536 + 1048576)
MAX_LOG_BYTES = 64 * 1024 * 1024


def expected_cases() -> list[dict[str, Any]]:
    result = []
    group = 0
    for executor in (1, 0):
        for size in (4, 65536, 1048576):
            for engine in ("CE_REQUEST", "SM"):
                group += 1
                base_seed = 0x6b8b4567 ^ size ^ (0x13579bdf * (executor + 1)) ^ (0 if engine == "CE_REQUEST" else 0x2468ace0)
                for step in ("PUSH_BEFORE", "PULL", "PUSH_AFTER"):
                    cid = len(result) + 1
                    source = 1 - executor if step == "PULL" else executor
                    result.append({"case_id": cid, "group": group, "step": step,
                                   "mode": "PULL" if step == "PULL" else "PUSH", "engine": engine,
                                   "source": source, "destination": 1 - source, "executor": executor,
                                   "bytes": size, "base_seed": f"{base_seed:08x}",
                                   "seed": f"{base_seed ^ ((cid * 0x9e3779b9) & 0xffffffff):08x}"})
    return result


def ensure(condition: bool, reason: str) -> None:
    if not condition:
        raise ValidationError(reason)


def records(lines: list[str], prefix: str) -> list[dict[str, Any]]:
    """Field values may include spaces, e.g. GPU and demangled kernel names."""
    result = []
    for number, line in enumerate(lines, 1):
        if not line.startswith(prefix + " "):
            continue
        marks = list(re.finditer(r"(?:^|\s)([A-Za-z0-9_]+)=", line))
        row: dict[str, Any] = {"line": number}
        ensure(bool(marks), f"{prefix}: missing fields")
        for index, mark in enumerate(marks):
            ensure(mark[1] not in row, f"{prefix}: duplicate field {mark[1]}")
            row[mark[1]] = line[mark.end():marks[index + 1].start() if index + 1 < len(marks) else len(line)].strip()
        result.append(row)
    return result


def one(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    ensure(len(rows) == 1, f"{label}: expected exactly one record")
    return rows[0]


def integer(row: dict[str, Any], key: str) -> int:
    ensure(isinstance(row.get(key), str) and re.fullmatch(r"[0-9]+", row[key]) is not None,
           f"missing or invalid integer {key}")
    return int(row[key])


def hexadecimal(value: Any, label: str) -> int:
    ensure(isinstance(value, str) and re.fullmatch(r"(?:0x)?[0-9a-fA-F]+", value) is not None,
           f"{label}: invalid hexadecimal value")
    return int(value, 16)


def equal(row: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    for key, value in expected.items():
        ensure(row.get(key) == str(value), f"{label}: {key} differs from required value")


def ordered(lines: list[str], prefix: str, key: str = "id", count: int = CASE_COUNT) -> list[dict[str, Any]]:
    rows = records(lines, prefix)
    ensure(len(rows) == count and [integer(row, key) for row in rows] == list(range(1, count + 1)),
           f"{prefix}: expected unique ordered {key}s 1 through {count}")
    return rows


def _audit_mappings(lines: list[str], cases: list[dict[str, Any]], data: list[dict[str, Any]],
                    sa_cases: list[dict[str, Any]], final: dict[str, Any]) -> dict[int, dict[str, Any]]:
    allocations = records(lines, "CE_ALLOCATION")
    ensure(len(allocations) == 2, "exactly two persistent allocations required")
    by_owner: dict[int, dict[str, Any]] = {}
    for row in allocations:
        owner = integer(row, "owner")
        ensure(owner in (0, 1) and owner not in by_owner, "allocation owner identity")
        equal(row, {"mode": "SHARED", "role": "shared", "allocation_bytes": ALLOCATION_BYTES}, "allocation")
        granularity = integer(row, "granularity")
        ensure(granularity > 0 and ALLOCATION_BYTES % granularity == 0, "allocation geometry")
        ensure(hexadecimal(row.get("va"), "allocation va") > 0 and hexadecimal(row.get("handle"), "allocation handle") > 0,
               "allocation address and handle must be nonzero")
        ensure(isinstance(row.get("nonce"), str) and re.fullmatch(r"[0-9a-f-]{36}", row["nonce"]) is not None,
               "allocation nonce")
        by_owner[owner] = row
    for key in ("va", "handle"):
        ensure(len({hexadecimal(row[key], key) for row in allocations}) == 2, f"allocations require distinct {key}")
    ensure(len({row["nonce"] for row in allocations}) == 2, "allocations require distinct nonces")
    addresses = sorted(hexadecimal(row["va"], "allocation va") for row in allocations)
    ensure(addresses[0] + ALLOCATION_BYTES <= addresses[1], "allocation virtual ranges overlap")
    ensure(max(row["line"] for row in allocations) < sa_cases[0]["line"], "all mappings must precede cases")
    access = records(lines, "CE_ACCESS")
    ensure(len(access) == 292, "expected 292 access queries")
    for row in access:
        owner, device = integer(row, "owner"), integer(row, "device")
        ensure(owner in by_owner and device in (0, 1), "access device identity")
        allocation = by_owner[owner]
        equal(row, {"mode": "SHARED", "role": "shared", "first": 3, "last": 3, "expected": 3,
                    "allocation_type": 1, "location_type": 1, "location_id": owner, "valid": 1}, "access")
        ensure(hexadecimal(row.get("va"), "access va") == hexadecimal(allocation["va"], "allocation va")
               and hexadecimal(row.get("last_va"), "last va") == hexadecimal(allocation["va"], "allocation va") + ALLOCATION_BYTES - 1,
               "access range differs from persistent allocation")
        ensure(row.get("stage") in ("created", "before_case", "after_case"), "unexpected access stage")

    def access_set(rows: list[dict[str, Any]], label: str) -> None:
        ensure(len(rows) == 4 and {(integer(row, "owner"), integer(row, "device")) for row in rows}
               == {(0, 0), (0, 1), (1, 0), (1, 1)}, f"{label}: both allocations require both access queries")

    created = [row for row in access if row["stage"] == "created"]
    access_set(created, "created")
    ensure(all(by_owner[integer(row, "owner")]["line"] < row["line"] < sa_cases[0]["line"] for row in created),
           "created query ordering")
    for index, case in enumerate(cases):
        previous = data[index - 1]["line"] if index else max(row["line"] for row in allocations)
        following = cases[index + 1]["line"] if index + 1 < CASE_COUNT else final["line"]
        access_set([row for row in access if row["stage"] == "before_case" and previous < row["line"] < case["line"]],
                   f"case {index + 1} before")
        access_set([row for row in access if row["stage"] == "after_case" and data[index]["line"] < row["line"] < following],
                   f"case {index + 1} after")
    gpu = records(lines, "CE_GPU")
    ensure(len(gpu) == 74, "expected 74 GPU identity checks")
    identities: dict[int, str] = {}
    for row in gpu:
        device = integer(row, "index")
        ensure(device in (0, 1), "GPU index")
        equal(row, {"bdf": ("0000:01:00.0", "0000:06:00.0")[device], "valid": 1}, "GPU identity")
        ensure(isinstance(row.get("uuid"), str) and re.fullmatch(r"[0-9a-f]{32}", row["uuid"]) is not None,
               "GPU UUID format")
        ensure(device not in identities or identities[device] == row["uuid"], "GPU UUID changed")
        identities[device] = row["uuid"]
    ensure(len(set(identities.values())) == 2, "GPU UUIDs must be distinct")
    ensure({integer(row, "index") for row in gpu[:2]} == {0, 1}
           and gpu[1]["line"] < min(row["line"] for row in allocations), "initial GPU identity queries")
    for index, case in enumerate(cases):
        pair = gpu[2 + 2 * index:4 + 2 * index]
        previous = data[index - 1]["line"] if index else max(row["line"] for row in allocations)
        ensure({integer(row, "index") for row in pair} == {0, 1}
               and all(previous < row["line"] < case["line"] for row in pair), "per-case GPU identity ordering")
    phases = records(lines, "CaskLogicCE")
    done = one([row for row in phases if row.get("phase") == "data_done"], "data_done")
    cleanup = one([row for row in phases if row.get("phase") == "cleanup_done"], "cleanup_done")
    frees = [row for row in phases if row.get("phase") == "allocation_free_begin"]
    finished = [row for row in phases if row.get("phase") == "allocation_free_done"]
    ensure(len(frees) == len(finished) == 2 and {integer(row, "s") for row in frees} == {0, 1}
           and {integer(row, "s") for row in finished} == {0, 1}, "two allocations freed once each")
    ensure(data[-1]["line"] < done["line"] < min(row["line"] for row in frees)
           and max(row["line"] for row in finished) < cleanup["line"] < final["line"], "allocations must remain live until all comparisons")
    for start, end in zip(frees, finished):
        ensure(start["s"] == end["s"] and start["line"] < end["line"], "allocation free pairing")
    return by_owner


def _audit_cupti(lines: list[str], cases: list[dict[str, Any]], begins: list[dict[str, Any]],
                 ends: list[dict[str, Any]], claims: list[dict[str, Any]], devices: dict[int, int]) -> list[dict[str, Any]]:
    ready = one(records(lines, "CUPTI_READY"), "CUPTI_READY")
    equal(ready, {"version": 24, "memcpy_record": 5, "ptop_record": 4, "kernel_record": 9}, "CUPTI ABI")
    ensure(ready["line"] < begins[0]["line"], "CUPTI initialization ordering")
    operations, callbacks = records(lines, "CUPTI_RECORD"), records(lines, "CUPTI_CALLBACK")
    correlation: dict[int, int] = {}

    def associate(corr: int, cid: int) -> None:
        ensure(corr > 0 and 1 <= cid <= CASE_COUNT, "CUPTI correlation/case range")
        ensure(corr not in correlation or correlation[corr] == cid, "ambiguous CUPTI correlation")
        correlation[corr] = cid

    for row in operations:
        if integer(row, "kind") == 39:
            associate(integer(row, "corr"), integer(row, "external"))
    for row in callbacks:
        associate(integer(row, "corr"), integer(row, "case"))
    for row in operations:
        ensure(integer(row, "case") == correlation.get(integer(row, "corr"), 0), "record case not derived from raw correlation")
    details = []
    for case, begin, end, claim in zip(cases, begins, ends, claims):
        cid, size = integer(case, "id"), integer(case, "bytes")
        ce = case["engine"] == "CE_REQUEST"
        current = [row for row in callbacks if integer(row, "case") == cid and row.get("is_d2d") == "1"]
        entries = [row for row in current if row.get("site") == "0"]
        exits = [row for row in current if row.get("site") == "1"]
        corr = integer(entries[-1], "corr") if entries else 0
        metadata = True
        if ce and len(entries) == len(exits) == 1:
            # cupti_trace.h buffers callbacks, then prints them in finish().
            # Their log line positions are not execution timestamps.
            metadata &= ends[-1]["line"] < entries[0]["line"] < exits[0]["line"] < claim["line"]
        for row in current:
            metadata &= (row.get("src") == case["src"] and row.get("dst") == case["dst"]
                         and integer(row, "bytes") == size and row.get("stream") == begin.get("stream")
                         and row.get("context") == begin.get("context") and integer(row, "corr") == corr
                         and row.get("site") in ("0", "1") and (row.get("site") != "1" or row.get("result") == "0"))
        driver = sum(integer(row, "kind") == 4 and integer(row, "corr") == corr and integer(row, "cbid") in (281, 423)
                     for row in operations)
        copies = kernels = host = unattributed = total = 0
        engines = True
        for row in operations:
            kind = integer(row, "kind")
            if kind not in (1, 22, 10):
                continue
            actual_case = correlation.get(integer(row, "corr"), 0)
            if actual_case != cid:
                if actual_case == 0 and integer(begin, "timestamp") <= integer(row, "start") <= integer(end, "timestamp"):
                    unattributed += 1
                continue
            metadata &= (all(integer(row, key) == integer(begin, key) for key in ("device", "context", "stream_id"))
                         and 0 < integer(row, "start") <= integer(row, "end")
                         and integer(begin, "timestamp") <= integer(row, "start")
                         and integer(row, "end") <= integer(end, "timestamp"))
            if kind in (1, 22):
                copies += 1
                total += integer(row, "bytes")
                host += (integer(row, "src_kind"), integer(row, "dst_kind")) != (3, 3)
                engines &= integer(row, "channel_type") == 2
                metadata &= integer(row, "copy_kind") in (8, 10) and (not ce or integer(row, "corr") == corr)
                if kind == 22:
                    metadata &= (integer(row, "src_device"), integer(row, "dst_device")) == (devices[integer(case, "s")], devices[integer(case, "d")])
            else:
                kernels += 1
                metadata &= "peer_push_kernel" in row.get("name", "")
        coverage = bool(metadata and not unattributed and
                        ((copies + kernels > 0 and len(entries) == len(exits) == driver == 1) if ce else (kernels == 1 and copies == 0)))
        observed = bool(ce and coverage and copies > 0 and kernels == 0 and engines and not host and total == size)
        computed = {"copies": copies, "kernels": kernels, "copy_bytes": total, "host_copies": host,
                    "unattributed": unattributed, "d2d_entries": len(entries), "d2d_exits": len(exits), "d2d_driver": driver,
                    "metadata_valid": int(metadata), "coverage_complete": int(coverage), "ce_observed": int(observed)}
        equal(claim, computed, f"case {cid} independently reconstructed CUPTI")
        ensure(coverage and ((observed and not host) if ce else (not current and driver == 0)), f"case {cid}: incomplete or inconsistent execution coverage")
        details.append({"case_id": cid, **computed})
    return details


def audit_records(log_text: str, payload_report: dict[str, Any]) -> dict[str, Any]:
    """Compose freshly computed in-memory payload analysis with raw log evidence.

    The CLI creates the report itself; this API does not authenticate arbitrary
    saved JSON reports. Synthetic reports in unit tests are not hardware evidence.
    """
    lines = log_text.splitlines()
    ensure(not any(line.startswith(("CE_ABORT ", "CUDA_ERROR ", "DRIVER_ERROR ", "CUPTI_ERROR ", "FATAL ")) for line in lines), "runtime error record present")
    expected = expected_cases()
    rows = {prefix: ordered(lines, prefix) for prefix in ("CE_CASE", "CE_DATA_RESULT", "SA_CASE", "PAYLOAD_CAPTURE", "CE_EXECUTOR", "CUPTI_CASE_BEGIN", "CUPTI_CASE_END", "CUPTI_CASE_RESULT")}
    cases, data = rows["CE_CASE"], rows["CE_DATA_RESULT"]
    begins, ends, claims = rows["CUPTI_CASE_BEGIN"], rows["CUPTI_CASE_END"], rows["CUPTI_CASE_RESULT"]
    final, summary = one(records(lines, "CE_PROGRAM_END"), "CE_PROGRAM_END"), one(records(lines, "CUPTI_SUMMARY"), "CUPTI_SUMMARY")
    protocol = one(records(lines, "SA_PROTOCOL"), "SA_PROTOCOL")
    equal(protocol, {"name": "same-allocation-bracket-v1", "allocations": 2, "comparisons": CASE_COUNT, "groups": GROUP_COUNT}, "protocol")
    ensure(protocol["line"] < cases[0]["line"], "protocol declaration ordering")
    ensure(not records(lines, "CE_MODE_BEGIN") and not records(lines, "CE_MODE_END"), "obsolete separate-allocation mode markers")
    allocations = _audit_mappings(lines, cases, data, rows["SA_CASE"], final)
    group_begin, group_end = ordered(lines, "SA_GROUP_BEGIN", "group", GROUP_COUNT), ordered(lines, "SA_GROUP_END", "group", GROUP_COUNT)
    for index, (begin, end) in enumerate(zip(group_begin, group_end)):
        spec = expected[index * 3]
        equal(begin, {"executor": spec["executor"], "engine": spec["engine"], "bytes": spec["bytes"], "base_seed": spec["base_seed"], "first_case": index * 3 + 1}, "group begin")
        equal(end, {"last_case": index * 3 + 3}, "group end")
        ensure(begin["line"] < rows["SA_CASE"][index * 3]["line"] < data[index * 3 + 2]["line"] < end["line"], "group bracket ordering")
        if index:
            ensure(group_end[index - 1]["line"] < begin["line"], "groups overlap or reorder")
    full = records(lines, "FULL_COMPARE")
    ensure(len(full) == 108, "expected 72 initialization and 36 payload comparisons")
    comparisons = {}
    for row in full:
        key = (integer(row, "iteration"), row.get("stage"))
        ensure(key not in comparisons and key[0] in range(1, CASE_COUNT + 1)
               and key[1] in ("source_initialized", "destination_poisoned", "peer_payload"), "duplicate or unknown comparison stage")
        comparisons[key] = row
    ensure(payload_report.get("analyzer") == "payload-diagnostics-offline-v1" and payload_report.get("case_count") == CASE_COUNT, "expected complete 36-case payload report")
    analyzed = payload_report.get("cases", [])
    ensure([case.get("case_id") for case in analyzed] == list(range(1, CASE_COUNT + 1)), "payload IDs not complete and ordered")
    ensure(sum(case.get("bytes", 0) for case in analyzed) == TOTAL_BYTES, "captured byte total differs")
    devices: dict[int, int] = {}
    for spec, begin in zip(expected, begins):
        for key, device in (("source_device", spec["source"]), ("target_device", spec["destination"])):
            value = integer(begin, key)
            ensure(device not in devices or devices[device] == value, "inconsistent CUPTI device identity")
            devices[device] = value
    ensure(len(set(devices.values())) == 2, "CUPTI devices must be distinct")
    failures = 0
    execution_identities: dict[int, tuple[Any, ...]] = {}
    for index, (spec, analyzed_case) in enumerate(zip(expected, analyzed)):
        cid = index + 1
        case, result, sa, capture, executor, begin, end, claim = (rows[prefix][index] for prefix in rows)
        label = f"case {cid}"
        for key in ("case_id", "mode", "engine", "source", "destination", "executor", "bytes", "seed"):
            ensure(analyzed_case.get(key) == spec[key], f"{label}: payload {key} differs from protocol")
        ensure(analyzed_case.get("metadata_counts_verified") is True and analyzed_case.get("same_allocations_across_modes") is True
               and analyzed_case.get("direct_route_proven") is False, f"{label}: missing payload qualification fields")
        for key in ("observed_sha256", "metadata_sha256"):
            ensure(isinstance(analyzed_case.get(key), str) and re.fullmatch(r"[0-9a-f]{64}", analyzed_case[key]) is not None, f"{label}: missing SHA256")
        common = {"engine": spec["engine"], "mode": spec["mode"], "executor": spec["executor"]}
        transfer = common | {"s": spec["source"], "d": spec["destination"], "bytes": spec["bytes"]}
        equal(case, transfer | {"seed": spec["seed"], "allocations_unchanged": 1}, label)
        equal(result, transfer | {"checked_words": spec["bytes"] // 4, "direct_route_proven": 0}, label)
        equal(sa, {"group": spec["group"], "step": spec["step"]}, label)
        for owner in (0, 1):
            for key, allocation_key in ((f"buffer{owner}", "va"), (f"handle{owner}", "handle")):
                ensure(hexadecimal(sa.get(key), label) == hexadecimal(allocations[owner][allocation_key], label), f"{label}: persistent {key} changed")
        for log_key, metadata_key, owner in (("src", "source_va", spec["source"]), ("dst", "destination_va", spec["destination"])):
            address = hexadecimal(allocations[owner]["va"], label)
            ensure(hexadecimal(case.get(log_key), label) == address == hexadecimal(analyzed_case.get(metadata_key), label)
                   == hexadecimal(begin.get(log_key), label), f"{label}: {log_key} differs from allocation/sidecar")
        equal(begin, transfer | {"device": devices[spec["executor"]]}, label)
        equal(executor, {"device": spec["executor"], "valid": 1}, label)
        ensure(executor.get("current") == executor.get("stream_context") and hexadecimal(executor.get("current"), label) > 0
               and executor.get("stream") == begin.get("stream") and hexadecimal(executor.get("stream"), label) > 0,
               f"{label}: executor context or stream differs")
        identity = (hexadecimal(executor["current"], label), hexadecimal(executor["stream"], label),
                    integer(begin, "context"), integer(begin, "stream_id"))
        ensure(spec["executor"] not in execution_identities or execution_identities[spec["executor"]] == identity,
               f"{label}: executing context/stream changed across the bracket protocol")
        execution_identities[spec["executor"]] = identity
        ensure(0 < integer(begin, "timestamp") <= integer(end, "timestamp"), f"{label}: invalid trace timestamps")
        equal(claim, common | {"direct_route_proven": 0}, label)
        counts = analyzed_case["counts"]
        ensure(all(type(counts.get(key)) is int and counts[key] >= 0 for key in ("correct_words", "sentinel_match_words", "other_words"))
               and sum(counts.values()) == spec["bytes"] // 4, f"{label}: invalid payload counts")
        mismatches = counts["sentinel_match_words"] + counts["other_words"]
        valid = int(mismatches == 0)
        failures += not valid
        equal(result, {"mismatches": mismatches, "valid": valid}, label)
        mismatch_fields = {}
        for name in ("first", "last"):
            item = analyzed_case[name + "_mismatch"]
            ensure((item is None) == bool(valid), f"{label}: mismatch bounds consistency")
            if item is not None:
                ensure(type(item.get("word_index")) is int and 0 <= item["word_index"] < spec["bytes"] // 4
                       and item.get("byte_offset") == 4 * item["word_index"], f"{label}: invalid mismatch offset")
                expected_word = payloads.word_pattern(item["word_index"], int(spec["seed"], 16))
                ensure(item.get("expected") == f"{expected_word:08x}", f"{label}: mismatch expected word does not encode offset/seed")
            mismatch_fields[name + "_mismatch_word"] = "null" if item is None else item["word_index"]
        if mismatches:
            ensure(analyzed_case["first_mismatch"]["word_index"] <= analyzed_case["last_mismatch"]["word_index"], f"{label}: mismatch order")
        equal(capture, counts | mismatch_fields | {"observed_file": f"case-{cid:03d}.observed.u32le", "complete": 1}, label)
        ensure(analyzed_case.get("observed_file") == f"case-{cid:03d}.observed.u32le" and analyzed_case.get("metadata_file") == f"case-{cid:03d}.json", f"{label}: filenames differ")
        initialization = []
        base_compare = {"s": spec["source"], "d": spec["destination"], "bytes": spec["bytes"], "checked_words": spec["bytes"] // 4}
        for stage, owner in (("source_initialized", spec["source"]), ("destination_poisoned", spec["destination"])):
            row = comparisons[(cid, stage)]
            equal(row, base_compare | {"owner": owner, "mismatches": 0, "valid": 1}, label)
            initialization.append(row)
        peer = comparisons[(cid, "peer_payload")]
        equal(peer, base_compare | {"owner": spec["destination"], "mismatches": mismatches, "valid": valid}, label)
        if mismatches:
            first = analyzed_case["first_mismatch"]
            equal(peer, {"first_index": first["word_index"], "first_got": first["observed"], "first_expected": first["expected"]}, label)
        else:
            ensure(not any(key in peer for key in ("first_index", "first_got", "first_expected")), f"{label}: mismatch fields on passing comparison")
        # SA_CASE may be immediately before or after CE_CASE; both must precede initialization.
        sequence = [case, *initialization, executor, begin, end, peer, capture, result]
        ensure(sa["line"] < initialization[0]["line"] and all(a["line"] < b["line"] for a, b in zip(sequence, sequence[1:])), f"{label}: invalid case ordering")
        if index:
            ensure(data[index - 1]["line"] < min(case["line"], sa["line"]), f"{label}: overlapping cases")
            ensure(integer(ends[index - 1], "timestamp") < integer(begin, "timestamp"), f"{label}: overlapping trace times")
        ensure(data[-1]["line"] < claim["line"] < summary["line"], f"{label}: trace classification ordering")
    cupti = _audit_cupti(lines, cases, begins, ends, claims, devices)
    equal(summary, {"trace_complete": 1, "cases": CASE_COUNT, "ce_cases": 18, "ce_observed": 18, "sm_observed": 18,
                    "dropped": 0, "errors": 0, "direct_route_proven": 0}, "CUPTI summary")
    rc = 5 if failures else 0
    equal(final, {"protocol_complete": 1, "comparisons": CASE_COUNT, "failures": failures, "trace_complete": 1,
                  "ce_cases": 18, "ce_observed": 18, "sm_observed": 18, "dropped": 0, "trace_errors": 0,
                  "direct_route_proven": 0, "rc": rc}, "program end")
    wrapper = []
    for marker in ("NATIVE_TEST_RC", "SCRIPT_RC"):
        found = [(number, line.split("=", 1)[1]) for number, line in enumerate(lines, 1) if line.startswith(marker + "=")]
        ensure(len(found) == 1 and found[0][1] == str(rc), f"{marker}: missing or inconsistent")
        wrapper.append(found[0][0])
    completed = [number for number, line in enumerate(lines, 1) if line == "PROBE_COMPLETED"]
    ensure(len(completed) == 1 and summary["line"] < final["line"] < wrapper[0] < completed[0] < wrapper[1], "completion marker ordering")
    return {
        "schema_version": 1, "validator": "same-allocation-protocol-validator-v1", "status": "COMPLETE_DIAGNOSTIC_EVIDENCE",
        "diagnostic_run_qualified": True, "protocol": "same-allocation-bracket-v1", "comparisons": CASE_COUNT,
        "groups": GROUP_COUNT, "persistent_allocations": 2, "access_queries": 292, "initialization_checks": 72,
        "gpu_identity_checks": 74, "passing_cases": CASE_COUNT - failures, "failing_cases": failures,
        "ce_observed": 18, "sm_observed": 18, "trace_complete": True, "cupti_independently_reconstructed": True,
        "program_rc": rc, "all_payloads_match": failures == 0, "same_software_allocations_across_modes": True,
        "direct_route_proven": False, "p2p_fix_established": False, "payload_bytes": TOTAL_BYTES,
        "qualification_scope": "Two persistent software VMM mappings, RW query results, bracket order, initialization, payload bytes and independently reconstructed CUPTI activity.",
        "evidence": {"path_note": "Logical labels only; hashes do not authenticate evidence origin.", "result_log": "result.log",
                     "payloads": [{"case_id": case["case_id"], "raw": "payloads/" + case["observed_file"],
                                   "raw_sha256": case["observed_sha256"], "metadata": "payloads/" + case["metadata_file"],
                                   "metadata_sha256": case["metadata_sha256"], "bytes": case["bytes"]} for case in analyzed]},
        "limitations": list(payload_report.get("limitations", [])) + [
            "Software VA/handle identity and access queries do not prove stable physical GPU PTEs or BAR1 mappings; kernel.log requires a separate audit.",
            "CUPTI does not expose final hardware descriptors or every possible internal staging path.",
            "A complete diagnostic run does not by itself establish a direct P2P route, a firmware fix, or the faulty component."],
        "cases": [case | {"group": spec["group"], "step": spec["step"]} for case, spec in zip(analyzed, expected)],
        "cupti_reconstruction": cupti,
    }


def analyze_payload_directory(directory: Path) -> dict[str, Any]:
    """Reuse the byte classifier, retaining identity fields from hashed sidecars."""
    report = payloads.analyze_directory(directory)
    for case in report["cases"]:
        path = Path(directory) / case["metadata_file"]
        ensure(path.is_file() and not path.is_symlink() and path.stat().st_size <= payloads.MAX_METADATA_BYTES, "metadata changed after classification")
        with path.open("rb") as handle:
            raw = handle.read(payloads.MAX_METADATA_BYTES + 1)
        ensure(len(raw) <= payloads.MAX_METADATA_BYTES and hashlib.sha256(raw).hexdigest() == case["metadata_sha256"], "metadata changed after classification")
        metadata = json.loads(raw, object_pairs_hook=payloads._unique_json_object, parse_constant=payloads._invalid_constant)
        for key in ("source_va", "destination_va", "same_allocations_across_modes", "direct_route_proven", "last_mismatch_word", "byte_order", "word_bytes"):
            ensure(key in metadata, f"missing same-allocation sidecar field {key}")
        ensure(metadata["byte_order"] == "little" and type(metadata["word_bytes"]) is int and metadata["word_bytes"] == 4, "sidecar word encoding")
        for key in ("source_va", "destination_va", "same_allocations_across_modes", "direct_route_proven"):
            case[key] = metadata[key]
    return report


def validate_run(log_path: Path, payload_directory: Path) -> dict[str, Any]:
    path = Path(log_path)
    ensure(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_LOG_BYTES, "log must be a regular non-symlink file up to 64 MiB")
    with path.open("rb") as handle:
        raw = handle.read(MAX_LOG_BYTES + 1)
    ensure(len(raw) <= MAX_LOG_BYTES, "log exceeds 64 MiB")
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise ValidationError("log must be UTF-8") from exc
    report = audit_records(text, analyze_payload_directory(payload_directory))
    report["evidence"]["result_log_sha256"] = hashlib.sha256(raw).hexdigest()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("payload_directory", type=Path)
    parser.add_argument("--output", type=Path, help="create a fresh report; existing files are never overwritten")
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
    except (ValidationError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
