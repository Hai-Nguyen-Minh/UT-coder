import csv
import tempfile
import unittest
from pathlib import Path

from core.benchmark.failed_selection import load_failed_pairs


class FailedBenchmarkSelectionTests(unittest.TestCase):
    def test_selects_false_pass_or_below_coverage_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Model", "TaskID", "Pass_at_1", "Pass_at_3", "Coverage"])
                writer.writerow(["qwen", "task_1", True, True, 100])
                writer.writerow(["qwen", "task_2", False, False, 100])
                writer.writerow(["llama", "task_3", True, True, 78])
                writer.writerow(["llama", "task_3", False, False, 0])

            failed = load_failed_pairs(path, minimum_coverage=80.0)

        self.assertEqual(failed, {("qwen", "task_2"), ("llama", "task_3")})

    def test_rejects_incompatible_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.csv"
            path.write_text("Model,TaskID\nqwen,task_1\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "missing columns"):
                load_failed_pairs(path, minimum_coverage=80.0)

    def test_current_schema_selects_invalid_or_incomplete_without_coverage_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow([
                    "Model", "TaskID", "EvaluationStatus", "Valid",
                    "ScoreComplete", "LineCoverage",
                ])
                writer.writerow(["qwen", "task_1", "VALID_STABLE", True, True, 40])
                writer.writerow(["qwen", "task_2", "UNSTABLE", False, False, 100])
                writer.writerow([
                    "llama", "task_3", "MUTATION_INCOMPLETE", True, False, 100
                ])

            failed = load_failed_pairs(path, minimum_coverage=80.0)

        self.assertEqual(failed, {("qwen", "task_2"), ("llama", "task_3")})
