"""Prepare verified dataset rows for high-quality few-shot retrieval.

The original ``tests`` field is never replaced: it remains the sandbox-verified
ground truth. ``rag_tests`` is a deterministic pytest-style representation used
only as model context.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from core.source_analyzer import analyze_python_source
from core.test_normalizer import normalize_rag_example


RAG_SCHEMA_VERSION = 2


def _stable_id(source: str, tests: str) -> str:
    digest = hashlib.sha256(f"{source}\0{tests}".encode("utf-8")).hexdigest()
    return f"py_{digest[:24]}"


def _has_assertion(test_tree: ast.AST) -> bool:
    for node in ast.walk(test_tree):
        if isinstance(node, ast.Assert):
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr.startswith("assert")
        ):
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "pytest"
            and node.func.attr in {"raises", "warns"}
        ):
            return True
    return False


def prepare_row(row: dict[str, Any]) -> dict[str, Any]:
    updated = dict(row)
    source = str(row.get("source", ""))
    tests = str(row.get("tests", ""))
    updated["dataset_id"] = _stable_id(source, tests)
    updated["language"] = "python"
    updated["rag_schema_version"] = RAG_SCHEMA_VERSION

    reasons: list[str] = []
    source_tree = None
    test_tree = None
    try:
        source_tree = ast.parse(source)
    except SyntaxError:
        reasons.append("source_syntax_error")
    try:
        test_tree = ast.parse(tests)
    except SyntaxError:
        reasons.append("test_syntax_error")

    if row.get("status") != "valid":
        reasons.append("status_not_valid")
    try:
        coverage = float(row.get("coverage") or 0.0)
    except (TypeError, ValueError):
        coverage = 0.0
    if coverage < 99.999999:
        reasons.append("coverage_below_100")
    if test_tree is not None and not _has_assertion(test_tree):
        reasons.append("no_assertion")

    analysis = analyze_python_source(source) if source_tree is not None else {"valid": False}
    eligibility = analysis.get("behavioral_eligibility", {})
    updated["rag_strategy"] = (
        "behavioral_probe" if eligibility.get("eligible") else "codegen_with_mocks_or_objects"
    )
    updated["rag_route_reasons"] = list(eligibility.get("reasons", []))

    normalized = ""
    if not reasons:
        normalized = normalize_rag_example(tests, source)
        try:
            ast.parse(normalized)
        except SyntaxError:
            reasons.append("normalized_test_syntax_error")

    updated["rag_eligible"] = not reasons
    updated["rag_quality_reasons"] = reasons
    if not reasons:
        updated["rag_tests"] = normalized
    else:
        updated.pop("rag_tests", None)
    return updated


def prepare_dataset(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Counter]:
    prepared = [prepare_row(row) for row in rows]
    stats = Counter()
    stats["rows"] = len(prepared)
    stats["rag_eligible"] = sum(bool(row["rag_eligible"]) for row in prepared)
    stats["unique_dataset_ids"] = len({row["dataset_id"] for row in prepared})
    for row in prepared:
        for reason in row["rag_quality_reasons"]:
            stats[f"rejected:{reason}"] += 1
        stats[f"strategy:{row['rag_strategy']}"] += 1
    return prepared, stats


def write_atomically(path: Path, rows: list[dict[str, Any]]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(rows, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    # Re-read before replacing the only workspace copy.
    json.loads(temp_path.read_text(encoding="utf-8"))
    temp_path.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--path",
        type=Path,
        default=Path(__file__).with_name("valid_dataset.json"),
    )
    parser.add_argument("--write", action="store_true")
    options = parser.parse_args()

    rows = json.loads(options.path.read_text(encoding="utf-8"))
    prepared, stats = prepare_dataset(rows)
    print(json.dumps(dict(sorted(stats.items())), indent=2))
    if options.write:
        write_atomically(options.path, prepared)
        print(f"Updated {options.path} using RAG schema v{RAG_SCHEMA_VERSION}")
    else:
        print("Dry run only; pass --write to update the dataset")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
