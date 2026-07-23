import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "core" / "benchmark" / "eval_dataset.json"
IMPORTED_ROOT = ROOT / "python_codegen_benchmark_20"


class EvalDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = json.loads(DATASET_PATH.read_text(encoding="utf-8"))

    def test_dataset_contains_exactly_fifty_unique_compilable_tasks(self):
        self.assertEqual(len(self.tasks), 50)
        self.assertEqual(
            [task["task_id"] for task in self.tasks],
            [f"unseen_{index}" for index in range(1, 51)],
        )
        for task in self.tasks:
            compile(task["source_code"], task["task_id"], "exec")

    def test_last_twenty_tasks_match_imported_reference_solutions(self):
        imported = self.tasks[30:]
        self.assertEqual(len(imported), 20)
        for task in imported:
            self.assertEqual(task["origin"], "python_codegen_benchmark_20")
            self.assertIs(task["embedded"], False)
            solution_path = IMPORTED_ROOT / task["benchmark_id"] / "solution.py"
            self.assertEqual(
                task["source_code"].strip(),
                solution_path.read_text(encoding="utf-8").strip(),
            )
