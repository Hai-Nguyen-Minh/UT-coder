"""Deterministic sandbox health check used before an expensive benchmark."""

from core.sandbox import get_sandbox
from core.sandbox.base import (
    SandboxInfrastructureError,
    detect_sandbox_infrastructure_error,
)


def run_sandbox_preflight():
    """Verify Ubuntu can execute pytest before spending any LLM tokens."""
    sandbox = get_sandbox("python")
    result = sandbox.run_test(
        "sandbox_preflight.py",
        "def add(left, right):\n    return left + right\n",
        (
            "import pytest\n"
            "from module_under_test import add\n\n"
            "def test_sandbox_preflight():\n"
            "    assert add(20, 22) == 42\n"
        ),
    )
    if result.success:
        return result

    infrastructure_error = detect_sandbox_infrastructure_error(
        result.stderr, result.error_log, result.stdout
    )
    if infrastructure_error:
        raise SandboxInfrastructureError(infrastructure_error)

    detail = (result.error_log or result.stderr or result.stdout).strip()
    if len(detail) > 500:
        detail = detail[-500:]
    raise SandboxInfrastructureError(
        f"Deterministic pytest preflight failed before benchmark: {detail or 'no output'}"
    )


def run_benchmark_preflight():
    """Verify both fast reflection and final quality-evaluation infrastructure."""

    sandbox_result = run_sandbox_preflight()
    from core.sandbox.internal.eval_runner import run_evaluator_preflight

    try:
        quality_result = run_evaluator_preflight()
    except Exception as exc:
        infrastructure_error = detect_sandbox_infrastructure_error(str(exc))
        raise SandboxInfrastructureError(
            infrastructure_error or str(exc)
        ) from exc
    return sandbox_result, quality_result


if __name__ == "__main__":
    preflight_result, quality_preflight_result = run_benchmark_preflight()
    print(
        "Sandbox preflight passed "
        f"(coverage={preflight_result.coverage or 0.0:.1f}%)."
    )
    print(
        "Evaluator preflight passed "
        f"(score={quality_preflight_result.final_score:.1f}, "
        f"mutants={quality_preflight_result.mutation.applicable})."
    )
