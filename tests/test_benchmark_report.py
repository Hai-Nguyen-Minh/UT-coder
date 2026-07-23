import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("matplotlib")
pytest.importorskip("pandas")
pytest.importorskip("seaborn")

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from core.benchmark.plot_eval_results import _generate_current_report


def test_report_counts_invalid_or_incomplete_rows_as_zero_overall():
    frame = pd.DataFrame([
        {
            "Model": "qwen", "TaskID": "task_1",
            "EvaluationStatus": "VALID_STABLE", "Valid": True,
            "ScoreComplete": True, "Stable": True, "FinalScore": 80,
            "LineCoverage": 100, "BranchCoverage": 90, "MutationScore": 70,
            "FirstAttemptAccepted": True, "EventualAccepted": True,
        },
        {
            "Model": "qwen", "TaskID": "task_2",
            "EvaluationStatus": "MUTATION_INCOMPLETE", "Valid": True,
            "ScoreComplete": False, "Stable": True, "FinalScore": None,
            "LineCoverage": 100, "BranchCoverage": 100, "MutationScore": None,
            "FirstAttemptAccepted": False, "EventualAccepted": True,
        },
        {
            "Model": "llama", "TaskID": "task_1",
            "EvaluationStatus": "VALID_FLAKY", "Valid": True,
            "ScoreComplete": True, "Stable": False, "FinalScore": 60,
            "LineCoverage": 80, "BranchCoverage": 70, "MutationScore": 50,
            "FirstAttemptAccepted": False, "EventualAccepted": True,
        },
        {
            "Model": "llama", "TaskID": "task_2",
            "EvaluationStatus": "UNSTABLE", "Valid": False,
            "ScoreComplete": False, "Stable": False, "FinalScore": None,
            "LineCoverage": None, "BranchCoverage": None, "MutationScore": None,
            "FirstAttemptAccepted": False, "EventualAccepted": False,
        },
    ])

    def close_plot(*_args, **_kwargs):
        plt.close()

    with tempfile.TemporaryDirectory() as directory, patch(
        "core.benchmark.plot_eval_results._save_current",
        side_effect=close_plot,
    ):
        output = Path(directory)
        summary = _generate_current_report(frame, output)

        qwen = summary.loc[summary["Model"] == "qwen"].iloc[0]
        llama = summary.loc[summary["Model"] == "llama"].iloc[0]
        assert qwen["OverallScore_mean"] == 40.0
        assert llama["OverallScore_mean"] == 30.0
        assert qwen["ValidScore_mean"] == 80.0
        assert (output / "benchmark_summary.csv").is_file()
        assert (output / "benchmark_status_counts.csv").is_file()
        assert (output / "benchmark_paired_comparison.csv").is_file()
