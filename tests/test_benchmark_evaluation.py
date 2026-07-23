import json
import tempfile
from pathlib import Path

from core.benchmark.evaluation_schema import (
    EvaluationResult,
    EvaluationStatus,
    MutationSummary,
    calculate_quality_score,
)
from core.sandbox.internal.eval_runner import (
    MODULE_NAME,
    _parse_coverage,
    parse_mutmut_progress,
)


def test_full_stable_score_uses_configured_weights():
    base, multiplier, final, normalized = calculate_quality_score(
        line_percent=100.0,
        branch_percent=80.0,
        mutation_percent=60.0,
        stability_passed_runs=3,
    )

    assert base == 72.0
    assert multiplier == 1.0
    assert final == 72.0
    assert normalized is False


def test_flaky_score_gets_exact_penalty():
    base, multiplier, final, _ = calculate_quality_score(
        line_percent=100.0,
        branch_percent=100.0,
        mutation_percent=100.0,
        stability_passed_runs=2,
    )

    assert base == 100.0
    assert multiplier == 0.8
    assert final == 80.0


def test_no_applicable_mutants_normalizes_only_coverage_weights():
    base, multiplier, final, normalized = calculate_quality_score(
        line_percent=60.0,
        branch_percent=30.0,
        mutation_percent=None,
        stability_passed_runs=3,
    )

    assert base == 40.0
    assert multiplier == 1.0
    assert final == 40.0
    assert normalized is True


def test_unstable_suite_always_scores_zero():
    assert calculate_quality_score(
        line_percent=100.0,
        branch_percent=100.0,
        mutation_percent=100.0,
        stability_passed_runs=1,
    )[:3] == (0.0, 0.0, 0.0)


def test_mutation_score_counts_timeout_segfault_and_no_test_policy():
    mutation = MutationSummary(
        killed=4,
        timed_out=1,
        segfault=1,
        survived=2,
        no_tests=2,
        suspicious=3,
        skipped=4,
        complete=True,
    )

    assert mutation.detected == 6
    assert mutation.undetected == 4
    assert mutation.applicable == 10
    assert mutation.excluded == 7
    assert mutation.score_percent == 60.0


def test_parse_current_mutmut_progress_format_strictly():
    output = "\r10/10  🎉 4  🫥 2  ⏰ 1  🤔 0  🙁 2  🔇 0  🛑 0  💥 1\n"

    mutation = parse_mutmut_progress(output, duration_seconds=12.5)

    assert mutation.complete is True
    assert mutation.total == 10
    assert mutation.killed == 4
    assert mutation.no_tests == 2
    assert mutation.timed_out == 1
    assert mutation.segfault == 1
    assert mutation.score_percent == 60.0


def test_partial_or_changed_mutmut_output_never_manufactures_score():
    partial = parse_mutmut_progress(
        "7/10  🎉 4  🫥 1  ⏰ 0  🤔 0  🙁 2  🔇 0  🛑 0  💥 0"
    )
    changed = parse_mutmut_progress("Killed: 4, Survived: 2")

    assert partial.complete is False
    assert partial.score_percent is None
    assert changed.complete is False
    assert "Unsupported" in changed.reason


def test_coverage_parser_keeps_statement_and_branch_rates_separate():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "coverage.json"
        path.write_text(
            json.dumps(
                {
                    "files": {
                        f"{MODULE_NAME}.py": {
                            "summary": {
                                "covered_lines": 8,
                                "num_statements": 10,
                                "covered_branches": 2,
                                "num_branches": 4,
                                "percent_covered": 70.0,
                            }
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        coverage = _parse_coverage(path)

    assert coverage.valid is True
    assert coverage.line_percent == 80.0
    assert coverage.branch_percent == 50.0


def test_source_without_branches_uses_line_rate_for_branch_score():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "coverage.json"
        path.write_text(
            json.dumps(
                {
                    "files": {
                        f"{MODULE_NAME}.py": {
                            "summary": {
                                "covered_lines": 3,
                                "num_statements": 4,
                                "covered_branches": 0,
                                "num_branches": 0,
                            }
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        coverage = _parse_coverage(path)

    assert coverage.line_percent == 75.0
    assert coverage.branch_percent == 75.0


def test_result_serialization_is_versioned_and_nested():
    result = EvaluationResult.empty(
        EvaluationStatus.NO_TESTS,
        source_code="def value(): return 1\n",
        test_code="",
    )

    payload = result.to_dict()

    assert payload["schema_version"] == "2.0"
    assert payload["evaluator_version"]
    assert payload["status"] == "NO_TESTS"
    assert len(payload["source_hash"]) == 64
