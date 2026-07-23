import unittest

from core.benchmark.metrics import evaluate_result


class BenchmarkMetricsTests(unittest.TestCase):
    def test_passing_pytest_below_coverage_gate_is_not_accepted(self):
        metrics = evaluate_result(
            {"success": True, "coverage": 78.57142857142857},
            attempts=1,
            minimum_coverage=80.0,
        )

        self.assertTrue(metrics["tests_passed"])
        self.assertFalse(metrics["coverage_met"])
        self.assertFalse(metrics["accepted"])
        self.assertFalse(metrics["pass_at_1"])
        self.assertFalse(metrics["pass_at_3"])

    def test_passing_pytest_at_coverage_gate_is_accepted(self):
        metrics = evaluate_result(
            {"success": True, "coverage": 80.0},
            attempts=1,
            minimum_coverage=80.0,
        )

        self.assertTrue(metrics["accepted"])
        self.assertTrue(metrics["pass_at_1"])
        self.assertTrue(metrics["pass_at_3"])

    def test_failed_pytest_is_not_accepted_even_with_full_coverage(self):
        metrics = evaluate_result(
            {"success": False, "coverage": 100.0},
            attempts=3,
            minimum_coverage=80.0,
        )

        self.assertFalse(metrics["accepted"])
        self.assertEqual(metrics["attempts"], 3)

    def test_invalid_coverage_artifact_is_never_accepted(self):
        metrics = evaluate_result(
            {"success": True, "coverage": 100.0, "coverage_valid": False},
            attempts=1,
            minimum_coverage=80.0,
        )

        self.assertFalse(metrics["coverage_met"])
        self.assertFalse(metrics["accepted"])
