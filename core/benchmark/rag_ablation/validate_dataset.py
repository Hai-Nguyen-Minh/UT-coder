"""Validate the project-aware RAG ablation dataset without modifying the repo.

The validator checks the dataset schema, Python syntax, hidden reference tests,
required project symbols, and exact source/AST overlap with the embedded corpus.
All executable validation happens in a fresh temporary directory.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import tempfile
import warnings
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
DEFAULT_DATASET = HERE / "dataset.json"
DEFAULT_EMBEDDED_DATASET = REPO_ROOT / "core" / "dataset" / "valid_dataset.json"
EXPECTED_CATEGORIES = {
    "internal_models",
    "injected_dependencies",
    "file_and_config",
    "stateful_components",
    "advanced_python",
}
REQUIRED_FIELDS = {
    "schema_version",
    "task_id",
    "category",
    "target_file",
    "target_source",
    "project_files",
    "required_symbols",
    "reference_tests",
}


class DatasetValidationError(ValueError):
    """Raised when one or more dataset invariants are violated."""


def _safe_relative_path(raw: str, *, field: str) -> PurePosixPath:
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts or "\\" in raw:
        raise DatasetValidationError(f"{field} must be a safe POSIX relative path: {raw!r}")
    if path.suffix != ".py":
        raise DatasetValidationError(f"{field} must point to a .py file: {raw!r}")
    return path


def _compile_python(source: str, filename: str) -> ast.Module:
    try:
        return ast.parse(source, filename=filename)
    except SyntaxError as exc:
        raise DatasetValidationError(f"Python syntax error in {filename}: {exc}") from exc


def _top_level_symbols(tree: ast.Module) -> set[str]:
    symbols: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    symbols.add(target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                symbols.add(alias.asname or alias.name.split(".")[0])
    return symbols


def _ast_fingerprint(source: str) -> str | None:
    try:
        # The historical embedded corpus contains a few legacy regex strings
        # such as "\s". They are still parseable, but Python emits unrelated
        # deprecation warnings while this validator only needs the AST shape.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            tree = ast.parse(source)
        return ast.dump(tree, annotate_fields=True, include_attributes=False)
    except (SyntaxError, TypeError):
        return None


def _load_embedded_fingerprints(path: Path) -> tuple[set[str], set[str]]:
    if not path.is_file():
        raise DatasetValidationError(f"Embedded dataset not found: {path}")
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetValidationError(f"Cannot read embedded dataset {path}: {exc}") from exc
    if not isinstance(records, list):
        raise DatasetValidationError("Embedded dataset must be a JSON list")

    exact: set[str] = set()
    fingerprints: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        source = record.get("source") or record.get("source_code")
        if not isinstance(source, str) or not source.strip():
            continue
        exact.add(source.strip())
        fingerprint = _ast_fingerprint(source)
        if fingerprint is not None:
            fingerprints.add(fingerprint)
    return exact, fingerprints


def _validate_record_shape(record: Any, index: int) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise DatasetValidationError(f"Record {index} must be an object")
    missing = REQUIRED_FIELDS - record.keys()
    if missing:
        raise DatasetValidationError(f"Record {index} is missing: {sorted(missing)}")
    if record["schema_version"] != 1:
        raise DatasetValidationError(f"{record.get('task_id', index)} has unsupported schema_version")
    for field in ("task_id", "category", "target_file", "target_source", "reference_tests"):
        if not isinstance(record[field], str) or not record[field].strip():
            raise DatasetValidationError(f"Record {index} field {field} must be a non-empty string")
    if not isinstance(record["project_files"], dict) or not record["project_files"]:
        raise DatasetValidationError(f"{record['task_id']} project_files must be a non-empty object")
    if not isinstance(record["required_symbols"], list) or not record["required_symbols"]:
        raise DatasetValidationError(f"{record['task_id']} required_symbols must be a non-empty list")
    return record


def _validate_record(
    record: dict[str, Any], embedded_exact: set[str], embedded_ast: set[str]
) -> None:
    task_id = record["task_id"]
    if record["category"] not in EXPECTED_CATEGORIES:
        raise DatasetValidationError(f"{task_id} has unknown category {record['category']!r}")

    target_path = _safe_relative_path(record["target_file"], field=f"{task_id}.target_file")
    target_tree = _compile_python(record["target_source"], str(target_path))
    del target_tree
    if record["target_source"].strip() in embedded_exact:
        raise DatasetValidationError(f"{task_id} target source exactly matches the embedded dataset")
    target_fingerprint = _ast_fingerprint(record["target_source"])
    if target_fingerprint in embedded_ast:
        raise DatasetValidationError(f"{task_id} target AST exactly matches the embedded dataset")

    support_trees: dict[str, ast.Module] = {}
    for raw_path, source in record["project_files"].items():
        path = _safe_relative_path(raw_path, field=f"{task_id}.project_files key")
        if path == target_path:
            raise DatasetValidationError(f"{task_id} duplicates target_file in project_files")
        if not isinstance(source, str) or not source.strip():
            raise DatasetValidationError(f"{task_id} support file {raw_path} must be non-empty")
        support_trees[raw_path] = _compile_python(source, raw_path)

    seen_required_files: set[str] = set()
    for group in record["required_symbols"]:
        if not isinstance(group, dict) or set(group) != {"file", "symbols"}:
            raise DatasetValidationError(
                f"{task_id} required_symbols entries need exactly 'file' and 'symbols'"
            )
        filename = group["file"]
        symbols = group["symbols"]
        if filename not in support_trees:
            raise DatasetValidationError(f"{task_id} required symbol file is missing: {filename}")
        if filename in seen_required_files:
            raise DatasetValidationError(f"{task_id} repeats required symbol file: {filename}")
        seen_required_files.add(filename)
        if not isinstance(symbols, list) or not symbols or any(
            not isinstance(symbol, str) or not symbol for symbol in symbols
        ):
            raise DatasetValidationError(f"{task_id} symbols for {filename} must be non-empty strings")
        if len(symbols) != len(set(symbols)):
            raise DatasetValidationError(f"{task_id} repeats required symbols for {filename}")
        available = _top_level_symbols(support_trees[filename])
        missing = set(symbols) - available
        if missing:
            raise DatasetValidationError(
                f"{task_id} required symbols absent from {filename}: {sorted(missing)}"
            )

    _compile_python(record["reference_tests"], f"test_{task_id}.py")


def _run_reference_tests(record: dict[str, Any], timeout_seconds: float) -> None:
    task_id = record["task_id"]
    with tempfile.TemporaryDirectory(prefix=f"utcoder-rag-{task_id}-") as raw_dir:
        workspace = Path(raw_dir)
        files = dict(record["project_files"])
        files[record["target_file"]] = record["target_source"]
        files[f"test_{task_id}.py"] = record["reference_tests"]
        for relative, source in files.items():
            destination = workspace.joinpath(*PurePosixPath(relative).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(source, encoding="utf-8")

        env = os.environ.copy()
        env["PYTHONPATH"] = str(workspace)
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", f"test_{task_id}.py"],
                cwd=workspace,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise DatasetValidationError(
                f"{task_id} reference tests exceeded {timeout_seconds:.1f}s"
            ) from exc
        if completed.returncode != 0:
            output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
            raise DatasetValidationError(f"{task_id} reference tests failed:\n{output[-4000:]}")


def validate_dataset(
    dataset_path: Path,
    embedded_dataset_path: Path,
    *,
    run_reference_tests: bool = True,
    timeout_seconds: float = 10.0,
) -> list[dict[str, Any]]:
    try:
        records = json.loads(dataset_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetValidationError(f"Cannot read dataset {dataset_path}: {exc}") from exc
    if not isinstance(records, list):
        raise DatasetValidationError("RAG ablation dataset must be a JSON list")
    if len(records) != 20:
        raise DatasetValidationError(f"Expected exactly 20 tasks, found {len(records)}")

    normalized = [_validate_record_shape(record, index) for index, record in enumerate(records)]
    task_ids = [record["task_id"] for record in normalized]
    duplicates = [task_id for task_id, count in Counter(task_ids).items() if count > 1]
    if duplicates:
        raise DatasetValidationError(f"Duplicate task IDs: {sorted(duplicates)}")
    target_files = [record["target_file"] for record in normalized]
    duplicate_targets = [name for name, count in Counter(target_files).items() if count > 1]
    if duplicate_targets:
        raise DatasetValidationError(f"Duplicate target files: {sorted(duplicate_targets)}")

    categories = Counter(record["category"] for record in normalized)
    expected_counts = {category: 4 for category in EXPECTED_CATEGORIES}
    if dict(categories) != expected_counts:
        raise DatasetValidationError(
            f"Expected four tasks in each category; found {dict(sorted(categories.items()))}"
        )

    embedded_exact, embedded_ast = _load_embedded_fingerprints(embedded_dataset_path)
    for record in normalized:
        _validate_record(record, embedded_exact, embedded_ast)
        if run_reference_tests:
            _run_reference_tests(record, timeout_seconds)
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--embedded-dataset", type=Path, default=DEFAULT_EMBEDDED_DATASET)
    parser.add_argument("--skip-reference-tests", action="store_true")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    try:
        records = validate_dataset(
            args.dataset,
            args.embedded_dataset,
            run_reference_tests=not args.skip_reference_tests,
            timeout_seconds=args.timeout,
        )
    except DatasetValidationError as exc:
        print(f"RAG ablation dataset validation failed: {exc}", file=sys.stderr)
        return 1
    categories = Counter(record["category"] for record in records)
    category_summary = ", ".join(f"{name}={count}" for name, count in sorted(categories.items()))
    mode = "syntax/schema" if args.skip_reference_tests else "syntax/schema + reference tests"
    print(f"RAG ablation dataset passed ({len(records)} tasks; {category_summary}; {mode}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
