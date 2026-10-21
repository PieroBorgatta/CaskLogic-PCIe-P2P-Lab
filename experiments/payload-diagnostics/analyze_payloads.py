#!/usr/bin/env python3
"""Validate and classify saved GPU payloads without opening a CUDA device.

The JSON sidecar records observations, not hardware qualification. Even a full
match cannot prove a direct peer route. Same-index sentinel matches do not prove
that no writes occurred: a write could have produced the sentinel value.

The source pattern is a bijection over uint32, so its inverse gives the unique
candidate source index for any value. A candidate inside this payload is an
equality hypothesis, not proof of the address used by a hardware transaction.
Source and complemented-source matches at other indices are independent and can
overlap. Exact repeated blocks, especially uniform blocks, do not prove aliasing.
"""

from __future__ import annotations

import argparse
from array import array
from collections import Counter
import hashlib
import heapq
import json
from pathlib import Path
import re
import struct
import sys
from typing import Any


MASK32 = 0xFFFFFFFF
MAX_BYTES = 8 * 1024 * 1024
MAX_METADATA_BYTES = 64 * 1024
MAX_RUNS = 128
MAX_DELTA_ENTRIES = 16
MAX_BLOCK_EXAMPLES = 8
PATTERN = "mix32-index-xor-seed-v1"
SENTINEL = "bitwise-not-expected"
INV_MUL_1 = pow(0x7FEB352D, -1, 1 << 32)
INV_MUL_2 = pow(0x846CA68B, -1, 1 << 32)
CLASSES = ("correct", "sentinel_match", "other")


class ValidationError(ValueError):
    """A payload or its sidecar is incomplete, unsafe to open, or inconsistent."""


def word_pattern(index: int, seed: int) -> int:
    x = (index ^ seed) & MASK32
    x ^= x >> 16
    x = (x * 0x7FEB352D) & MASK32
    x ^= x >> 15
    x = (x * 0x846CA68B) & MASK32
    return x ^ (x >> 16)


def pattern_index(value: int, seed: int) -> int:
    """Invert the source pattern; the caller must check the payload bounds."""
    x = value ^ (value >> 16)
    x = (x * INV_MUL_2) & MASK32
    x = x ^ (x >> 15) ^ (x >> 30)
    x = (x * INV_MUL_1) & MASK32
    x ^= x >> 16
    return x ^ seed


def matched_indices(value: int, seed: int, word_count: int) -> tuple[int | None, int | None]:
    """Return independent in-range source and sentinel candidate indices."""
    source_index = pattern_index(value, seed)
    sentinel_index = pattern_index(value ^ MASK32, seed)
    return (
        source_index if source_index < word_count else None,
        sentinel_index if sentinel_index < word_count else None,
    )


def _integer(value: Any, name: str, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValidationError(f"{name} must be an integer in [{minimum}, {maximum or 'unbounded'}]")
    return value


def validate_metadata(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise ValidationError("metadata must be a JSON object")
    required = (
        "schema_version", "case_id", "engine", "mode", "source", "destination", "executor",
        "bytes", "seed", "observed_file", "pattern", "sentinel", "first_mismatch_word",
        "correct_words", "sentinel_match_words", "other_words",
    )
    for name in required:
        if name not in metadata:
            raise ValidationError(f"missing metadata field: {name}")
    if _integer(metadata["schema_version"], "schema_version") != 1:
        raise ValidationError("unsupported schema_version")
    _integer(metadata["case_id"], "case_id")
    if metadata["engine"] not in ("SM", "CE_REQUEST"):
        raise ValidationError("engine must be SM or CE_REQUEST")
    if metadata["mode"] not in ("PUSH", "PULL"):
        raise ValidationError("mode must be PUSH or PULL")
    for name in ("source", "destination", "executor"):
        _integer(metadata[name], name)
    if metadata["source"] == metadata["destination"]:
        raise ValidationError("source and destination must be different GPUs")
    executor = metadata["source"] if metadata["mode"] == "PUSH" else metadata["destination"]
    if metadata["executor"] != executor:
        raise ValidationError("executor is inconsistent with PUSH/PULL mode")
    byte_count = _integer(metadata["bytes"], "bytes", 4, MAX_BYTES)
    if byte_count % 4:
        raise ValidationError("bytes must be a multiple of four")
    seed = metadata["seed"]
    if not isinstance(seed, str) or re.fullmatch(r"[0-9a-fA-F]{8}", seed) is None:
        raise ValidationError("seed must contain exactly eight hexadecimal digits")
    if metadata["pattern"] != PATTERN:
        raise ValidationError("unsupported source pattern")
    if metadata["sentinel"] != SENTINEL:
        raise ValidationError("unsupported sentinel pattern")
    if "byte_order" in metadata and metadata["byte_order"] != "little":
        raise ValidationError("byte_order must be little")
    if "word_bytes" in metadata and (type(metadata["word_bytes"]) is not int or metadata["word_bytes"] != 4):
        raise ValidationError("word_bytes must be the integer 4")
    # A canonical basename also excludes absolute paths, traversal, and nested paths.
    expected_file = f"case-{metadata['case_id']:03d}.observed.u32le"
    if metadata["observed_file"] != expected_file:
        raise ValidationError(f"observed_file must be the basename {expected_file!r}")
    words = byte_count // 4
    counts = [
        _integer(metadata[name], name, 0, words)
        for name in ("correct_words", "sentinel_match_words", "other_words")
    ]
    if sum(counts) != words:
        raise ValidationError("the three mutually exclusive counts must sum to the word count")
    first = metadata["first_mismatch_word"]
    if first is not None:
        _integer(first, "first_mismatch_word", 0, words - 1)
    if (first is None) != (metadata["correct_words"] == words):
        raise ValidationError("first_mismatch_word is inconsistent with correct_words")
    if "last_mismatch_word" in metadata:
        last = metadata["last_mismatch_word"]
        if last is not None:
            _integer(last, "last_mismatch_word", 0, words - 1)
        if (last is None) != (first is None) or (last is not None and last < first):
            raise ValidationError("last_mismatch_word is inconsistent with first_mismatch_word")
    return metadata


def _mismatch(index: int, observed: int, expected: int) -> dict[str, Any]:
    return {
        "word_index": index,
        "byte_offset": 4 * index,
        "observed": f"{observed:08x}",
        "expected": f"{expected:08x}",
        "sentinel": f"{expected ^ MASK32:08x}",
    }


def _repeat_blocks(raw: bytes, block_bytes: int) -> dict[str, Any]:
    # Byte strings, rather than hash equality, establish that a repeat is exact.
    seen: dict[bytes, tuple[int, int]] = {}
    examples: list[dict[str, Any]] = []
    repeats = distinct_repeats = uniform_repeats = 0
    complete_blocks = len(raw) // block_bytes
    for block_index in range(complete_blocks):
        block = raw[block_index * block_bytes:(block_index + 1) * block_bytes]
        previous = seen.get(block)
        if previous is None:
            seen[block] = (block_index, 1)
            continue
        first_index, count = previous
        seen[block] = (first_index, count + 1)
        repeats += 1
        distinct_repeats += count == 1
        uniform = block == block[:4] * (block_bytes // 4)
        uniform_repeats += uniform
        if len(examples) < MAX_BLOCK_EXAMPLES:
            examples.append({
                "first_block_index": first_index,
                "repeated_block_index": block_index,
                "first_byte_offset": first_index * block_bytes,
                "repeated_byte_offset": block_index * block_bytes,
                "block_sha256": hashlib.sha256(block).hexdigest(),
                "uniform_u32": f"{int.from_bytes(block[:4], 'little'):08x}" if uniform else None,
            })
    return {
        "block_bytes": block_bytes,
        "alignment_origin_byte": 0,
        "complete_blocks": complete_blocks,
        "ignored_tail_bytes": len(raw) % block_bytes,
        "unique_blocks": len(seen),
        "repeated_blocks": repeats,
        "distinct_repeated_patterns": distinct_repeats,
        "uniform_repeated_blocks": uniform_repeats,
        "nonuniform_repeated_blocks": repeats - uniform_repeats,
        "max_examples": MAX_BLOCK_EXAMPLES,
        "omitted_examples": repeats - len(examples),
        "examples": examples,
        "interpretation": "Exact repetition is not proof of addressing aliasing; uniform repeats are especially nonspecific.",
    }


def summarize_payload(metadata: dict[str, Any], raw: bytes) -> dict[str, Any]:
    metadata = validate_metadata(metadata)
    if len(raw) != metadata["bytes"]:
        raise ValidationError(f"payload length {len(raw)} differs from bytes={metadata['bytes']}")
    words = len(raw) // 4
    seed = int(metadata["seed"], 16)
    counts: Counter[str] = Counter({name: 0 for name in CLASSES})
    zero_words = ones_words = source_other = sentinel_other = 0
    first_mismatch = last_mismatch = None
    runs: list[dict[str, Any]] = []
    run_counts: Counter[str] = Counter({name: 0 for name in CLASSES})
    total_runs = 0
    run_start = 0
    run_class: str | None = None
    # At the maximum input size this bounded histogram uses about 16 MiB.
    deltas = array("I", [0]) * (2 * words - 1)
    delta_origin = words - 1
    distinct_deltas = 0

    def finish_run(end_exclusive: int) -> None:
        nonlocal total_runs
        if run_class is None:
            return
        total_runs += 1
        run_counts[run_class] += 1
        if len(runs) < MAX_RUNS:
            runs.append({
                "class": run_class,
                "first_word": run_start,
                "last_word": end_exclusive - 1,
                "first_byte_offset": run_start * 4,
                "end_byte_offset_exclusive": end_exclusive * 4,
                "words": end_exclusive - run_start,
            })

    for index, (value,) in enumerate(struct.iter_unpack("<I", raw)):
        expected = word_pattern(index, seed)
        if value == expected:
            kind = "correct"
        elif value == (expected ^ MASK32):
            kind = "sentinel_match"
        else:
            kind = "other"
        counts[kind] += 1
        if kind != "correct":
            mismatch = _mismatch(index, value, expected)
            if first_mismatch is None:
                first_mismatch = mismatch
            last_mismatch = mismatch
        if kind != run_class:
            finish_run(index)
            run_start, run_class = index, kind
        zero_words += value == 0
        ones_words += value == MASK32
        source_index, sentinel_index = matched_indices(value, seed, words)
        if source_index is not None and source_index != index:
            source_other += 1
            delta_slot = source_index - index + delta_origin
            distinct_deltas += deltas[delta_slot] == 0
            deltas[delta_slot] += 1
        if sentinel_index is not None and sentinel_index != index:
            sentinel_other += 1
    finish_run(words)

    computed = {f"{name}_words": counts[name] for name in CLASSES}
    computed["first_mismatch_word"] = None if first_mismatch is None else first_mismatch["word_index"]
    if "last_mismatch_word" in metadata:
        computed["last_mismatch_word"] = None if last_mismatch is None else last_mismatch["word_index"]
    for name, value in computed.items():
        if metadata[name] != value:
            raise ValidationError(f"case {metadata['case_id']}: recorded {name}={metadata[name]!r}, computed {value!r}")
    top_deltas = heapq.nsmallest(
        MAX_DELTA_ENTRIES,
        ((-count, slot - delta_origin) for slot, count in enumerate(deltas) if count),
    )
    return {
        "case_id": metadata["case_id"],
        "engine": metadata["engine"],
        "mode": metadata["mode"],
        "source": metadata["source"],
        "destination": metadata["destination"],
        "executor": metadata["executor"],
        "bytes": len(raw),
        "words": words,
        "seed": f"{seed:08x}",
        "pattern": PATTERN,
        "sentinel": SENTINEL,
        "observed_file": metadata["observed_file"],
        "observed_sha256": hashlib.sha256(raw).hexdigest(),
        "metadata_counts_verified": True,
        "hardware_qualification": "unknown",
        "counts": {f"{name}_words": counts[name] for name in CLASSES},
        "first_mismatch": first_mismatch,
        "last_mismatch": last_mismatch,
        "overlapping_value_counts": {
            "all_zero_words": zero_words,
            "all_ones_words": ones_words,
            "note": "These counts overlap with the three mutually exclusive word classes.",
        },
        "other_index_matches": {
            "equal_source_other_index_words": source_other,
            "equal_sentinel_other_index_words": sentinel_other,
            "note": "Independent equality counts; they may overlap with each other and with any word class. They are not transaction addresses.",
        },
        "source_index_delta_histogram": {
            "definition": "matched_source_index - observed_word_index; same-index matches excluded",
            "total_matches": source_other,
            "distinct_deltas": distinct_deltas,
            "max_entries": MAX_DELTA_ENTRIES,
            "omitted_distinct_deltas": max(0, distinct_deltas - len(top_deltas)),
            "top": [{"delta_words": delta, "delta_bytes": 4 * delta, "words": -count} for count, delta in top_deltas],
        },
        "class_runs": {
            "total_runs": total_runs,
            "runs_by_class": dict(run_counts),
            "max_emitted_runs": MAX_RUNS,
            "omitted_runs": total_runs - len(runs),
            "runs": runs,
        },
        "repeated_blocks": [_repeat_blocks(raw, 64), _repeat_blocks(raw, 4096)],
    }


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValidationError(f"non-finite JSON constant: {value}")


def analyze_case(metadata_path: Path) -> dict[str, Any]:
    metadata_path = Path(metadata_path)
    if metadata_path.is_symlink() or not metadata_path.is_file():
        raise ValidationError(f"metadata must be a regular, non-symlink file: {metadata_path.name}")
    if metadata_path.stat().st_size > MAX_METADATA_BYTES:
        raise ValidationError("metadata exceeds 64 KiB")
    metadata_raw = metadata_path.read_bytes()
    if len(metadata_raw) > MAX_METADATA_BYTES:
        raise ValidationError("metadata exceeds 64 KiB")
    try:
        metadata = json.loads(metadata_raw, object_pairs_hook=_unique_json_object, parse_constant=_invalid_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"invalid JSON metadata: {metadata_path.name}: {exc}") from exc
    validate_metadata(metadata)
    if metadata_path.name != f"case-{metadata['case_id']:03d}.json":
        raise ValidationError("metadata filename does not match case_id")
    observed_path = metadata_path.parent / metadata["observed_file"]
    if observed_path.is_symlink() or not observed_path.is_file():
        raise ValidationError(f"payload missing or not a regular, non-symlink file: {observed_path.name}")
    if observed_path.stat().st_size != metadata["bytes"]:
        raise ValidationError(f"payload length differs from bytes: {observed_path.name}")
    # The preceding size check bounds ordinary input; read MAX_BYTES+1 also bounds
    # a file that grows while being read. The complete length is checked again.
    with observed_path.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    result = summarize_payload(metadata, raw)
    result["metadata_file"] = metadata_path.name
    result["metadata_sha256"] = hashlib.sha256(metadata_raw).hexdigest()
    return result


def analyze_directory(directory: Path) -> dict[str, Any]:
    directory = Path(directory)
    if not directory.is_dir():
        raise ValidationError(f"not an input directory: {directory}")
    metadata_paths = sorted(directory.glob("case-*.json"))
    raw_paths = list(directory.glob("case-*.observed.u32le"))
    if not metadata_paths:
        raise ValidationError("no case metadata files found")
    cases = [analyze_case(path) for path in metadata_paths]
    cases.sort(key=lambda item: item["case_id"])
    referenced = {case["observed_file"] for case in cases}
    orphans = {path.name for path in raw_paths} - referenced
    if orphans:
        raise ValidationError(f"payloads without case metadata: {', '.join(sorted(orphans))}")
    return {
        "schema_version": 1,
        "analyzer": "payload-diagnostics-offline-v1",
        "case_count": len(cases),
        "hardware_qualification": "unknown",
        "qualification_note": "Payload files alone cannot qualify a hardware run. Review the complete protocol log, initialization checks, synchronization, mapping, and execution evidence separately. This report does not establish a direct P2P route or a P2P fix.",
        "limitations": [
            "A same-index sentinel match does not prove absence of writes; the same value could have been written.",
            "The source hash is bijective over uint32; an in-range inverse is only an equality hypothesis about the source index.",
            "Source and sentinel matches at other indices are independent and may overlap.",
            "Repeated blocks, especially uniform blocks, do not prove addressing aliasing.",
            "SHA256 records the bytes analyzed; it does not authenticate their origin.",
            "Word patterns alone cannot locate a fault in a requester, mapping, bridge, or host fabric.",
        ],
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="directory containing case-NNN.json and raw little-endian payloads")
    parser.add_argument("--output", type=Path, help="create a new JSON report; existing files are never overwritten")
    args = parser.parse_args(argv)
    try:
        report = analyze_directory(args.directory)
        encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output is None:
            sys.stdout.write(encoded)
        else:
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(encoded)
            print(f"Created {args.output}")
    except (ValidationError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
