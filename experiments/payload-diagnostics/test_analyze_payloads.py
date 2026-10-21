"""CPU-only fixtures for classifications and invalid/incomplete evidence."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest

import analyze_payloads as analyzer


def expected_words(count, seed=0x12345678):
    return [analyzer.word_pattern(index, seed) for index in range(count)]


def make_case(values, seed=0x12345678, case_id=1):
    expected = expected_words(len(values), seed)
    correct = sum(got == want for got, want in zip(values, expected))
    sentinel = sum(got == (want ^ analyzer.MASK32) for got, want in zip(values, expected))
    first = next((index for index, (got, want) in enumerate(zip(values, expected)) if got != want), None)
    metadata = {
        "schema_version": 1, "case_id": case_id, "engine": "SM", "mode": "PUSH",
        "source": 0, "destination": 1, "executor": 0, "bytes": len(values) * 4,
        "seed": f"{seed:08x}", "observed_file": f"case-{case_id:03d}.observed.u32le",
        "pattern": analyzer.PATTERN, "sentinel": analyzer.SENTINEL,
        "first_mismatch_word": first, "correct_words": correct,
        "sentinel_match_words": sentinel, "other_words": len(values) - correct - sentinel,
    }
    return metadata, struct.pack(f"<{len(values)}I", *values)


class PayloadClassificationTests(unittest.TestCase):
    def analyze(self, values, seed=0x12345678):
        metadata, raw = make_case(values, seed)
        return analyzer.summarize_payload(metadata, raw)

    def test_pattern_inverse_and_known_zero(self):
        self.assertEqual(analyzer.word_pattern(0, 0), 0)
        self.assertEqual(analyzer.word_pattern(13755, 0), 0xF723C4EA)
        for seed in (0, 0x12345678, 0xFFFFFFFF):
            for index in (0, 1, 65535, 262144, 0x7FFFFFFF, 0xFFFFFFFF):
                with self.subTest(seed=seed, index=index):
                    self.assertEqual(analyzer.pattern_index(analyzer.word_pattern(index, seed), seed), index)

    def test_fully_correct_and_raw_hash(self):
        metadata, raw = make_case(expected_words(32))
        result = analyzer.summarize_payload(metadata, raw)
        self.assertEqual(result["counts"], {"correct_words": 32, "sentinel_match_words": 0, "other_words": 0})
        self.assertIsNone(result["first_mismatch"])
        self.assertIsNone(result["last_mismatch"])
        self.assertEqual(result["observed_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["hardware_qualification"], "unknown")
        self.assertEqual(result["class_runs"]["total_runs"], 1)

    def test_entire_initial_sentinel_retained(self):
        values = [value ^ analyzer.MASK32 for value in expected_words(64)]
        result = self.analyze(values)
        self.assertEqual(result["counts"], {"correct_words": 0, "sentinel_match_words": 64, "other_words": 0})
        self.assertEqual(result["first_mismatch"]["word_index"], 0)
        self.assertEqual(result["last_mismatch"]["byte_offset"], 252)

    def test_all_ones_and_zeros_overlap_with_classes(self):
        # With seed zero the expected word at index 0 is zero; its sentinel is all ones.
        ones = self.analyze([analyzer.MASK32] * 8, seed=0)
        self.assertEqual(ones["counts"], {"correct_words": 0, "sentinel_match_words": 1, "other_words": 7})
        self.assertEqual(ones["overlapping_value_counts"]["all_ones_words"], 8)
        zeros = self.analyze([0] * 8, seed=0)
        self.assertEqual(zeros["counts"], {"correct_words": 1, "sentinel_match_words": 0, "other_words": 7})
        self.assertEqual(zeros["overlapping_value_counts"]["all_zero_words"], 8)
        self.assertEqual(zeros["first_mismatch"]["word_index"], 1)
        self.assertEqual(zeros["other_index_matches"]["equal_source_other_index_words"], 7)

    def test_partial_write_classes_and_offsets(self):
        expected = expected_words(12)
        values = expected[:4] + [value ^ analyzer.MASK32 for value in expected[4:8]] + [0xFFFFFFFF] * 4
        result = self.analyze(values)
        self.assertEqual(result["counts"], {"correct_words": 4, "sentinel_match_words": 4, "other_words": 4})
        self.assertEqual(result["first_mismatch"], {
            "word_index": 4, "byte_offset": 16, "observed": f"{expected[4] ^ analyzer.MASK32:08x}",
            "expected": f"{expected[4]:08x}", "sentinel": f"{expected[4] ^ analyzer.MASK32:08x}",
        })
        self.assertEqual(result["last_mismatch"]["byte_offset"], 44)
        self.assertEqual([run["class"] for run in result["class_runs"]["runs"]], ["correct", "sentinel_match", "other"])
        self.assertEqual([run["words"] for run in result["class_runs"]["runs"]], [4, 4, 4])

    def test_shifted_source_pattern_delta_histogram(self):
        expected = expected_words(16)
        result = self.analyze(expected[1:] + expected[:1])
        self.assertEqual(result["counts"]["correct_words"], 0)
        self.assertEqual(result["other_index_matches"]["equal_source_other_index_words"], 16)
        self.assertEqual(result["source_index_delta_histogram"]["distinct_deltas"], 2)
        self.assertEqual(result["source_index_delta_histogram"]["top"], [
            {"delta_words": 1, "delta_bytes": 4, "words": 15},
            {"delta_words": -15, "delta_bytes": -60, "words": 1},
        ])

    def test_source_and_sentinel_other_index_matches_can_overlap(self):
        # This fixed complement pair was found in the actual uint32 pattern.
        value = analyzer.word_pattern(13755, 0)
        self.assertEqual(value, analyzer.word_pattern(57226, 0) ^ analyzer.MASK32)
        self.assertEqual(analyzer.matched_indices(value, 0, 65536), (13755, 57226))
        values = expected_words(65536, seed=0)
        values[0] = value
        result = self.analyze(values, seed=0)
        self.assertEqual(result["counts"]["other_words"], 1)
        self.assertEqual(result["other_index_matches"]["equal_source_other_index_words"], 1)
        self.assertGreaterEqual(result["other_index_matches"]["equal_sentinel_other_index_words"], 3)

    def test_delta_histogram_is_capped_without_losing_distinct_total(self):
        result = self.analyze(list(reversed(expected_words(64))))
        histogram = result["source_index_delta_histogram"]
        self.assertEqual(histogram["total_matches"], 64)
        self.assertEqual(histogram["distinct_deltas"], 64)
        self.assertEqual(len(histogram["top"]), analyzer.MAX_DELTA_ENTRIES)
        self.assertEqual(histogram["omitted_distinct_deltas"], 64 - analyzer.MAX_DELTA_ENTRIES)
        self.assertTrue(all(entry["words"] == 1 for entry in histogram["top"]))

    def test_exact_nonuniform_repeated_64_and_4096_byte_blocks(self):
        result = self.analyze(expected_words(16) * 128)
        small, large = result["repeated_blocks"]
        self.assertEqual(small["complete_blocks"], 128)
        self.assertEqual(small["repeated_blocks"], 127)
        self.assertEqual(small["distinct_repeated_patterns"], 1)
        self.assertEqual(small["nonuniform_repeated_blocks"], 127)
        self.assertEqual(len(small["examples"]), analyzer.MAX_BLOCK_EXAMPLES)
        self.assertEqual(small["omitted_examples"], 127 - analyzer.MAX_BLOCK_EXAMPLES)
        self.assertEqual(large["repeated_blocks"], 1)
        self.assertEqual(large["examples"][0]["repeated_byte_offset"], 4096)
        self.assertIsNone(large["examples"][0]["uniform_u32"])

    def test_uniform_repeats_and_incomplete_block_tail(self):
        result = self.analyze([0xFFFFFFFF] * 33)
        small, large = result["repeated_blocks"]
        self.assertEqual(small["uniform_repeated_blocks"], 1)
        self.assertEqual(small["nonuniform_repeated_blocks"], 0)
        self.assertEqual(small["ignored_tail_bytes"], 4)
        self.assertEqual(small["examples"][0]["uniform_u32"], "ffffffff")
        self.assertEqual(large["complete_blocks"], 0)
        self.assertEqual(large["ignored_tail_bytes"], 132)

    def test_runs_are_capped_without_losing_totals(self):
        values = expected_words(300)
        for index in range(1, len(values), 2):
            values[index] ^= analyzer.MASK32
        result = self.analyze(values)
        runs = result["class_runs"]
        self.assertEqual(runs["total_runs"], 300)
        self.assertEqual(runs["runs_by_class"], {"correct": 150, "sentinel_match": 150, "other": 0})
        self.assertEqual(len(runs["runs"]), analyzer.MAX_RUNS)
        self.assertEqual(runs["omitted_runs"], 300 - analyzer.MAX_RUNS)


class EvidenceValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.metadata, self.raw = make_case(expected_words(32))
        self.metadata_path = self.directory / "case-001.json"
        self.payload_path = self.directory / self.metadata["observed_file"]
        self.write_case()

    def write_case(self):
        self.metadata_path.write_text(json.dumps(self.metadata), encoding="utf-8")
        self.payload_path.write_bytes(self.raw)

    def test_directory_report_requires_no_hardware_and_unknown_qualification(self):
        self.metadata["future_extra_field"] = {"allowed": True}
        self.write_case()
        result = analyzer.analyze_directory(self.directory)
        self.assertEqual(result["case_count"], 1)
        self.assertEqual(result["hardware_qualification"], "unknown")
        self.assertTrue(result["cases"][0]["metadata_counts_verified"])

    def test_inconsistent_recorded_counts_and_first_mismatch_rejected(self):
        self.metadata.update(correct_words=31, sentinel_match_words=0, other_words=1, first_mismatch_word=0)
        self.write_case()
        with self.assertRaisesRegex(analyzer.ValidationError, "recorded correct_words"):
            analyzer.analyze_case(self.metadata_path)
        values = expected_words(32)
        values[4] ^= analyzer.MASK32
        self.metadata, self.raw = make_case(values)
        self.metadata["first_mismatch_word"] = 5
        self.write_case()
        with self.assertRaisesRegex(analyzer.ValidationError, "recorded first_mismatch_word"):
            analyzer.analyze_case(self.metadata_path)

    def test_invalid_schema_fields_rejected(self):
        bad_values = {
            "schema_version": [2, True], "case_id": [-1, True],
            "engine": ["CE", "unknown"], "mode": ["COPY"], "executor": [1],
            "source": [-1, True], "destination": [0], "bytes": [0, 3, 129, analyzer.MAX_BYTES + 4],
            "seed": ["0x12345678", "bad", 123], "pattern": ["unknown-v2"],
            "sentinel": ["constant-ff"], "first_mismatch_word": [0, 32, True],
            "correct_words": [True, -1, 31], "sentinel_match_words": [-1], "other_words": [1],
        }
        original = self.metadata.copy()
        for name, values in bad_values.items():
            for value in values:
                with self.subTest(name=name, value=value):
                    candidate = original | {name: value}
                    with self.assertRaises(analyzer.ValidationError):
                        analyzer.validate_metadata(candidate)

    def test_every_required_metadata_field_must_be_present(self):
        for name in self.metadata:
            with self.subTest(missing=name):
                candidate = self.metadata.copy()
                del candidate[name]
                with self.assertRaisesRegex(analyzer.ValidationError, "missing metadata field"):
                    analyzer.validate_metadata(candidate)

    def test_optional_encoding_and_last_mismatch_fields(self):
        values = expected_words(32)
        values[4] ^= analyzer.MASK32
        values[20] ^= analyzer.MASK32
        metadata, raw = make_case(values)
        metadata.update(byte_order="little", word_bytes=4, last_mismatch_word=20)
        result = analyzer.summarize_payload(metadata, raw)
        self.assertEqual(result["last_mismatch"]["word_index"], 20)
        for name, value in (("byte_order", "big"), ("word_bytes", 8), ("word_bytes", True),
                            ("last_mismatch_word", None), ("last_mismatch_word", 3),
                            ("last_mismatch_word", 32), ("last_mismatch_word", True)):
            with self.subTest(name=name, value=value):
                with self.assertRaises(analyzer.ValidationError):
                    analyzer.validate_metadata(metadata | {name: value})
        with self.assertRaisesRegex(analyzer.ValidationError, "recorded last_mismatch_word"):
            analyzer.summarize_payload(metadata | {"last_mismatch_word": 21}, raw)
        passing, raw = make_case(expected_words(32))
        analyzer.summarize_payload(passing | {"last_mismatch_word": None}, raw)

    def test_truncated_and_oversized_payload_rejected(self):
        for raw in (self.raw[:-1], self.raw + b"\x00\x00\x00\x00"):
            with self.subTest(length=len(raw)):
                self.payload_path.write_bytes(raw)
                with self.assertRaisesRegex(analyzer.ValidationError, "length"):
                    analyzer.analyze_case(self.metadata_path)

    def test_missing_payload_and_metadata_rejected(self):
        self.payload_path.unlink()
        with self.assertRaisesRegex(analyzer.ValidationError, "payload missing"):
            analyzer.analyze_directory(self.directory)
        self.write_case()
        self.metadata_path.unlink()
        with self.assertRaisesRegex(analyzer.ValidationError, "no case metadata"):
            analyzer.analyze_directory(self.directory)

    def test_orphan_payload_is_rejected_even_with_valid_case(self):
        (self.directory / "case-002.observed.u32le").write_bytes(self.raw)
        with self.assertRaisesRegex(analyzer.ValidationError, "without case metadata"):
            analyzer.analyze_directory(self.directory)

    def test_traversal_absolute_path_and_symlink_rejected(self):
        for path in ("../case-001.observed.u32le", "/tmp/case-001.observed.u32le", "sub/case-001.observed.u32le"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(analyzer.ValidationError, "basename"):
                    analyzer.validate_metadata(self.metadata | {"observed_file": path})
        self.payload_path.unlink()
        external = self.directory / "external.raw"
        external.write_bytes(self.raw)
        self.payload_path.symlink_to(external)
        with self.assertRaisesRegex(analyzer.ValidationError, "non-symlink"):
            analyzer.analyze_case(self.metadata_path)

    def test_case_id_and_filename_must_match(self):
        wrong = self.directory / "case-002.json"
        self.metadata_path.rename(wrong)
        with self.assertRaisesRegex(analyzer.ValidationError, "filename"):
            analyzer.analyze_case(wrong)

    def test_duplicate_keys_nonfinite_and_invalid_json_rejected(self):
        for contents in ('{"schema_version":1,"schema_version":1}', '{"x":NaN}', '{broken'):
            with self.subTest(contents=contents):
                self.metadata_path.write_text(contents, encoding="utf-8")
                with self.assertRaises(analyzer.ValidationError):
                    analyzer.analyze_case(self.metadata_path)

    def test_cli_creates_report_but_never_overwrites(self):
        output = self.directory / "analysis.json"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(analyzer.main([str(self.directory), "--output", str(output)]), 0)
        original = output.read_bytes()
        self.assertEqual(json.loads(original)["case_count"], 1)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(analyzer.main([str(self.directory), "--output", str(output)]), 2)
        self.assertEqual(output.read_bytes(), original)

    def test_invalid_case_does_not_create_output_report(self):
        output = self.directory / "analysis.json"
        self.payload_path.write_bytes(b"broken")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(analyzer.main([str(self.directory), "--output", str(output)]), 2)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
