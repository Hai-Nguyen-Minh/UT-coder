import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from core.benchmark.evaluation_schema import MutationSummary
from core.sandbox.internal.eval_runner import (
    EvaluationConfig,
    _ProcessOutcome,
    _run_mutation,
    evaluate_python_test,
)


FAST_CONFIG = EvaluationConfig(
    compile_timeout_seconds=10,
    collection_timeout_seconds=15,
    baseline_timeout_seconds=15,
    coverage_timeout_seconds=20,
    mutation_timeout_seconds=15,
)


def _completed_mutation(*_args, **_kwargs):
    return (
        MutationSummary(
            killed=3,
            survived=1,
            total=4,
            completed=4,
            complete=True,
        ),
        _ProcessOutcome(0, "4/4", "", 0.01),
    )


def test_evaluator_runs_hard_gates_coverage_and_scoring():
    source = """def classify(value):
    if value > 0:
        return "positive"
    return "non-positive"
"""
    tests = """from module_under_test import classify

def test_positive():
    assert classify(1) == "positive"

def test_non_positive():
    assert classify(0) == "non-positive"
"""
    with tempfile.TemporaryDirectory() as directory, patch(
        "core.sandbox.internal.eval_runner._run_mutation",
        side_effect=_completed_mutation,
    ):
        result = evaluate_python_test(
            file_name="task.py",
            source_code=source,
            test_code=tests,
            artifact_dir=directory,
            config=FAST_CONFIG,
        )

        assert result.status == "VALID_STABLE"
        assert result.valid is True
        assert result.score_complete is True
        assert result.stability_passed_runs == 3
        assert result.coverage.line_percent == 100.0
        assert result.coverage.branch_percent == 100.0
        assert result.mutation.score_percent == 75.0
        assert result.final_score == 86.25
        assert (Path(directory) / "eval_result.json").is_file()
        assert (Path(directory) / "generated_test.py").is_file()


def test_all_skipped_suite_is_invalid_before_coverage_and_mutation():
    with patch("core.sandbox.internal.eval_runner._run_mutation") as mutation:
        result = evaluate_python_test(
            file_name="task.py",
            source_code="def value():\n    return 1\n",
            test_code=(
                "import pytest\n"
                "@pytest.mark.skip(reason='not implemented')\n"
                "def test_value():\n"
                "    assert True\n"
            ),
            config=FAST_CONFIG,
        )

    assert result.status == "ALL_SKIPPED"
    assert result.valid is False
    assert result.score_complete is True
    assert result.final_score == 0.0
    mutation.assert_not_called()


def test_compile_failure_short_circuits_every_expensive_stage():
    with patch("core.sandbox.internal.eval_runner._run_mutation") as mutation:
        result = evaluate_python_test(
            file_name="task.py",
            source_code="def value():\n    return 1\n",
            test_code="def test_broken(:\n    pass\n",
            config=FAST_CONFIG,
        )

    assert result.status == "TEST_COMPILE_FAILED"
    assert result.valid is False
    assert result.score_complete is True
    assert result.final_score == 0.0
    mutation.assert_not_called()


def test_incomplete_mutation_keeps_validity_but_withholds_final_score():
    incomplete = MutationSummary(complete=False, reason="global timeout")
    process = _ProcessOutcome(None, "", "", 15.0, timed_out=True)
    with patch(
        "core.sandbox.internal.eval_runner._run_mutation",
        return_value=(incomplete, process),
    ):
        result = evaluate_python_test(
            file_name="task.py",
            source_code="def value():\n    return 1\n",
            test_code=(
                "from module_under_test import value\n"
                "def test_value():\n"
                "    assert value() == 1\n"
            ),
            config=FAST_CONFIG,
        )

    assert result.status == "MUTATION_INCOMPLETE"
    assert result.valid is True
    assert result.score_complete is False
    assert result.final_score is None


def test_project_support_files_are_available_to_all_pytest_stages_and_artifacts():
    source = """from domain.models import Price

def total(price: Price, quantity: int) -> int:
    return price.cents * quantity
"""
    tests = """from domain.models import Price
from module_under_test import total

def test_total():
    assert total(Price(cents=125), 2) == 250
"""
    project_files = {
        "domain/__init__.py": "",
        "domain/models.py": (
            "from dataclasses import dataclass\n\n"
            "@dataclass(frozen=True)\n"
            "class Price:\n"
            "    cents: int\n"
        ),
    }
    with tempfile.TemporaryDirectory() as directory, patch(
        "core.sandbox.internal.eval_runner._run_mutation",
        side_effect=_completed_mutation,
    ):
        result = evaluate_python_test(
            file_name="pricing.py",
            source_code=source,
            test_code=tests,
            project_files=project_files,
            artifact_dir=directory,
            config=FAST_CONFIG,
        )

        assert result.status == "VALID_STABLE"
        assert result.coverage.line_percent == 100.0
        assert (
            Path(directory) / "project_files" / "domain" / "models.py"
        ).read_text(encoding="utf-8") == project_files["domain/models.py"]


def test_mutation_workspace_contains_support_files_but_only_mutates_target():
    observed: dict[str, str] = {}

    def fake_run_process(_command, *, workspace, **_kwargs):
        observed["support"] = (
            workspace / "src" / "domain" / "models.py"
        ).read_text(encoding="utf-8")
        observed["config"] = (workspace / "pyproject.toml").read_text(
            encoding="utf-8"
        )
        return _ProcessOutcome(0, "", "", 0.01)

    with tempfile.TemporaryDirectory() as directory, patch(
        "core.sandbox.internal.eval_runner._run_process",
        side_effect=fake_run_process,
    ):
        _run_mutation(
            Path(directory),
            source_code="def value():\n    return 1\n",
            test_code="def test_value():\n    assert True\n",
            project_files={"domain/models.py": "class Model:\n    pass\n"},
            config=FAST_CONFIG,
        )

    assert observed["support"] == "class Model:\n    pass\n"
    assert 'only_mutate = ["src/module_under_test.py"]' in observed["config"]


@pytest.mark.parametrize(
    "unsafe_path",
    ["../escape.py", "/tmp/escape.py", r"C:\\tmp\\escape.py", "a/../../b.py"],
)
def test_evaluator_rejects_project_path_traversal(unsafe_path):
    with pytest.raises(ValueError, match="Unsafe project file path"):
        evaluate_python_test(
            file_name="task.py",
            source_code="def value():\n    return 1\n",
            test_code="def test_value():\n    assert True\n",
            project_files={unsafe_path: "pass\n"},
            config=FAST_CONFIG,
        )
