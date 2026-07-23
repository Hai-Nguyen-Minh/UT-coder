"""Acceptance rules for benchmark results."""

from __future__ import annotations

from typing import Any

DEFAULT_MINIMUM_COVERAGE = 80.0


def evaluate_result(
    result: dict[str, Any],
    *,
    attempts: int,
    minimum_coverage: float,
) -> dict[str, Any]:
    """Require both passing pytest and the configured coverage threshold."""
    tests_passed = bool(result.get("success", False))
    coverage = float(result.get("coverage", 0.0) or 0.0)
    coverage_valid = bool(
        result.get("coverage_valid", result.get("coverage") is not None)
    )
    coverage_met = coverage_valid and coverage >= minimum_coverage
    accepted = tests_passed and coverage_met
    normalized_attempts = max(1, int(attempts or 0))
    return {
        "tests_passed": tests_passed,
        "coverage": coverage,
        "coverage_valid": coverage_valid,
        "coverage_met": coverage_met,
        "accepted": accepted,
        "pass_at_1": accepted and normalized_attempts <= 1,
        "pass_at_3": accepted,
        "attempts": normalized_attempts,
    }
