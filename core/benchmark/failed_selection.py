"""Select failed model-task pairs for a focused benchmark rerun."""

from __future__ import annotations

import csv
from pathlib import Path


_TRUE_VALUES = {"1", "true", "yes", "y"}


def _as_bool(value: object) -> bool:
    return str(value or "").strip().lower() in _TRUE_VALUES


def load_failed_pairs(
    results_path: str | Path,
    *,
    minimum_coverage: float,
) -> set[tuple[str, str]]:
    """Return pairs that failed pytest/Pass@3 or the strict coverage gate."""
    path = Path(results_path)
    if not path.is_file():
        raise FileNotFoundError(f"Benchmark results CSV not found: {path}")

    failed: set[tuple[str, str]] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        is_current = {"EvaluationStatus", "Valid", "ScoreComplete"}.issubset(fields)
        required = (
            {"Model", "TaskID", "EvaluationStatus", "Valid", "ScoreComplete"}
            if is_current
            else {"Model", "TaskID", "Pass_at_3", "Coverage"}
        )
        missing = required - fields
        if missing:
            raise ValueError(
                "Benchmark results CSV is missing columns: "
                + ", ".join(sorted(missing))
            )
        for row in reader:
            model = str(row.get("Model", "")).strip()
            task_id = str(row.get("TaskID", "")).strip()
            if not model or not task_id:
                continue
            if is_current:
                row_failed = (
                    not _as_bool(row.get("Valid"))
                    or not _as_bool(row.get("ScoreComplete"))
                )
            else:
                try:
                    coverage = float(row.get("Coverage", 0.0) or 0.0)
                except (TypeError, ValueError):
                    coverage = 0.0
                row_failed = (
                    not _as_bool(row.get("Pass_at_3"))
                    or coverage < minimum_coverage
                )
            if row_failed:
                failed.add((model, task_id))
    return failed
