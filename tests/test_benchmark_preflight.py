import unittest
from unittest.mock import patch

from core.sandbox.base import SandboxInfrastructureError, SandboxResult
from core.sandbox.preflight import run_benchmark_preflight, run_sandbox_preflight


class FakeSandbox:
    def __init__(self, result):
        self.result = result

    def run_test(self, file_name, source_code, test_code):
        return self.result


class BenchmarkPreflightTests(unittest.TestCase):
    def test_successful_preflight_returns_result(self):
        result = SandboxResult(
            success=True,
            stdout="1 passed",
            stderr="",
            coverage=100.0,
        )
        with patch(
            "core.sandbox.preflight.get_sandbox",
            return_value=FakeSandbox(result),
        ):
            self.assertIs(run_sandbox_preflight(), result)

    def test_previous_ubuntu_exec_failure_aborts_preflight(self):
        result = SandboxResult(
            success=False,
            stdout="",
            stderr=(
                'File "/app/core/sandbox/resource_runner.py", line 80\n'
                "BlockingIOError: [Errno 11] Resource temporarily unavailable"
            ),
        )
        with patch(
            "core.sandbox.preflight.get_sandbox",
            return_value=FakeSandbox(result),
        ):
            with self.assertRaisesRegex(
                SandboxInfrastructureError, "RLIMIT_NPROC"
            ):
                run_sandbox_preflight()

    def test_deterministic_test_failure_is_still_treated_as_server_failure(self):
        result = SandboxResult(
            success=False,
            stdout="",
            stderr="pytest could not collect the preflight test",
        )
        with patch(
            "core.sandbox.preflight.get_sandbox",
            return_value=FakeSandbox(result),
        ):
            with self.assertRaisesRegex(
                SandboxInfrastructureError, "Deterministic pytest preflight failed"
            ):
                run_sandbox_preflight()

    def test_full_preflight_requires_quality_evaluator_too(self):
        sandbox_result = SandboxResult(success=True, stdout="", stderr="")
        quality_result = object()
        with patch(
            "core.sandbox.preflight.run_sandbox_preflight",
            return_value=sandbox_result,
        ), patch(
            "core.sandbox.internal.eval_runner.run_evaluator_preflight",
            return_value=quality_result,
        ):
            self.assertEqual(
                run_benchmark_preflight(),
                (sandbox_result, quality_result),
            )

    def test_quality_preflight_failure_is_infrastructure_failure(self):
        sandbox_result = SandboxResult(success=True, stdout="", stderr="")
        with patch(
            "core.sandbox.preflight.run_sandbox_preflight",
            return_value=sandbox_result,
        ), patch(
            "core.sandbox.internal.eval_runner.run_evaluator_preflight",
            side_effect=RuntimeError("Could not start mutmut: missing"),
        ):
            with self.assertRaisesRegex(SandboxInfrastructureError, "mutmut"):
                run_benchmark_preflight()
