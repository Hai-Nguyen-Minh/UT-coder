"""Run the paired project-context RAG ablation after the main benchmark.

The workbench evaluates one fixed model on the same 20 project tasks with RAG
disabled and enabled. Results are append-only and resumable; a manifest prevents
mixing runs produced by different datasets or evaluator/generator revisions.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

from core.benchmark.evaluate_models import RESULT_COLUMNS, _result_row
from core.benchmark.evaluation_schema import (
    EVALUATOR_VERSION,
    SCHEMA_VERSION,
    EvaluationResult,
    EvaluationStatus,
)
from core.benchmark.metrics import DEFAULT_MINIMUM_COVERAGE, evaluate_result
from core.config import get_config
from core.llm import clear_llm_cache
from core.ollama_memory import OllamaUnloadError, unload_ollama_model
from core.sandbox.base import SandboxInfrastructureError
from core.sandbox.internal.eval_runner import evaluate_python_test
from core.sandbox.preflight import run_benchmark_preflight

from .validate_dataset import (
    DEFAULT_DATASET,
    DEFAULT_EMBEDDED_DATASET,
    validate_dataset,
)


ABLATION_SCHEMA_VERSION = "1.0"
MODEL_ID = "qwen2.5-coder:7b"
MAX_RETRIES = 3
PROJECT_CONTEXT_K = 4
FEWSHOT_CANDIDATE_K = 4
HERE = Path(__file__).resolve().parent
DEFAULT_RESULTS = HERE / "results.csv"
DEFAULT_MANIFEST = HERE / "manifest.json"

EXPERIMENT_COLUMNS = [
    "AblationSchemaVersion",
    "Condition",
    "RAGEnabled",
    "ProjectContextK",
    "FewshotCandidateK",
    "Category",
    "ProjectHash",
    "RequiredSymbols",
    "FirstAttemptExecutionStatus",
    "FirstAttemptCompileCollectionPassed",
    "FirstAttemptTestsPassed",
    "FirstAttemptCoverage",
    "FirstAttemptContextError",
    "FirstAttemptContextErrorCategory",
]
ABLATION_RESULT_COLUMNS = EXPERIMENT_COLUMNS + RESULT_COLUMNS

_CONTEXT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "internal_import",
        re.compile(
            r"ModuleNotFoundError|ImportError|cannot import name|No module named",
            re.IGNORECASE,
        ),
    ),
    (
        "missing_symbol",
        re.compile(
            r"NameError|AttributeError|has no attribute|is not defined",
            re.IGNORECASE,
        ),
    ),
    (
        "signature_or_constructor",
        re.compile(
            r"TypeError:.*(?:argument|positional|keyword|constructor|__init__)",
            re.IGNORECASE,
        ),
    ),
    (
        "async_or_protocol_contract",
        re.compile(
            r"AsyncMock|awaitable|was never awaited|"
            r"cannot be used in.*await.*expression|context manager|protocol",
            re.IGNORECASE,
        ),
    ),
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _project_hash(record: dict[str, Any]) -> str:
    payload = {
        "target_file": record["target_file"],
        "target_source": record["target_source"],
        "project_files": record["project_files"],
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return _sha256_bytes(canonical)


def _required_symbols(record: dict[str, Any]) -> str:
    values: list[str] = []
    for requirement in record.get("required_symbols", []):
        file_name = str(requirement.get("file", ""))
        for symbol in requirement.get("symbols", []):
            values.append(f"{file_name}:{symbol}")
    return ";".join(values)


def _manifest_payload(dataset_path: Path) -> dict[str, Any]:
    root = HERE.parents[2]
    cfg = get_config()
    return {
        "ablation_schema_version": ABLATION_SCHEMA_VERSION,
        "evaluator_schema_version": SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "model": MODEL_ID,
        "temperature": cfg.get("llm", {}).get("temperature"),
        "max_retries": MAX_RETRIES,
        "minimum_line_coverage": DEFAULT_MINIMUM_COVERAGE,
        "project_context_k": PROJECT_CONTEXT_K,
        "fewshot_candidate_k": FEWSHOT_CANDIDATE_K,
        "conditions": ["RAG_OFF", "RAG_ON"],
        "dataset_sha256": _sha256_file(dataset_path),
        "generator_sha256": _sha256_file(root / "core" / "generator.py"),
        "evaluator_sha256": _sha256_file(
            root / "core" / "sandbox" / "internal" / "eval_runner.py"
        ),
    }


def _ensure_manifest(
    manifest_path: Path,
    results_path: Path,
    expected: dict[str, Any],
) -> None:
    if manifest_path.exists():
        current = json.loads(manifest_path.read_text(encoding="utf-8"))
        comparable = {key: current.get(key) for key in expected}
        if comparable != expected:
            mismatches = [
                key for key, value in expected.items() if current.get(key) != value
            ]
            raise ValueError(
                "RAG ablation manifest does not match this run; archive the old "
                f"results before continuing. Changed: {', '.join(mismatches)}"
            )
        return
    if results_path.exists() and results_path.stat().st_size:
        raise ValueError(
            f"Refusing to append {results_path} without its provenance manifest."
        )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **expected,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _existing_keys(results_path: Path) -> set[tuple[str, str, str, str]]:
    if not results_path.exists() or results_path.stat().st_size == 0:
        return set()
    with results_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(ABLATION_RESULT_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                "Existing RAG ablation CSV uses an incompatible schema. Missing: "
                + ", ".join(sorted(missing))
            )
        return {
            (
                row.get("Condition", ""),
                row.get("TaskID", ""),
                row.get("ProjectHash", ""),
                row.get("EvaluatorVersion", ""),
            )
            for row in reader
            if row.get("Model") == MODEL_ID
        }


def _condition_order(index: int, selection: str) -> list[bool]:
    if selection == "rag":
        return [True]
    if selection == "no-rag":
        return [False]
    # Counterbalance order so one arm is not always warmed up or run first.
    return [False, True] if index % 2 == 0 else [True, False]


def _context_error(first_result: dict[str, Any]) -> tuple[bool, str]:
    status = str(first_result.get("execution_status", ""))
    log = "\n".join(
        str(first_result.get(name, "") or "")
        for name in ("error_log", "stderr")
    )
    if status == "test_compile_error":
        # Syntax is an AI failure, but it does not demonstrate missing project
        # context. It is captured by the compile/collection success metric.
        return False, ""
    if status in {"collection_error", "no_tests_collected"}:
        for category, pattern in _CONTEXT_PATTERNS:
            if pattern.search(log):
                return True, category
        return False, ""
    for category, pattern in _CONTEXT_PATTERNS:
        if pattern.search(log):
            return True, category
    return False, ""


def _compile_collection_passed(first_result: dict[str, Any]) -> bool:
    status = str(first_result.get("execution_status", ""))
    collected = first_result.get("tests_collected")
    return bool(
        status
        not in {
            "compile_timeout",
            "source_compile_error",
            "test_compile_error",
            "collection_error",
            "no_tests_collected",
            "pytest_internal_error",
            "pytest_usage_error",
        }
        and isinstance(collected, int)
        and collected > 0
    )


def _write_jsonl(
    path: Path,
    *,
    record: dict[str, Any],
    condition: str,
    project_hash: str,
    first_result: dict[str, Any],
    generation_metrics: dict[str, Any],
    evaluation: EvaluationResult,
) -> None:
    payload = {
        "ablation_schema_version": ABLATION_SCHEMA_VERSION,
        "condition": condition,
        "rag_enabled": condition == "RAG_ON",
        "model": MODEL_ID,
        "task_id": record["task_id"],
        "category": record["category"],
        "project_hash": project_hash,
        "target_file": record["target_file"],
        "required_symbols": record["required_symbols"],
        "first_attempt": first_result,
        "generation": generation_metrics,
        "evaluation": evaluation.to_dict(),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _selected_runs(
    records: list[dict[str, Any]], selection: str
) -> Iterable[tuple[int, dict[str, Any], bool]]:
    for index, record in enumerate(records):
        for enabled in _condition_order(index, selection):
            yield index, record, enabled


def run_ablation(
    *,
    dataset_path: Path = DEFAULT_DATASET,
    embedded_dataset_path: Path = DEFAULT_EMBEDDED_DATASET,
    results_path: Path = DEFAULT_RESULTS,
    manifest_path: Path = DEFAULT_MANIFEST,
    condition: str = "both",
    run_preflight: bool = True,
) -> bool:
    """Run or resume the paired 20-task ablation; return True on completion."""
    records = validate_dataset(
        dataset_path,
        embedded_dataset_path,
        run_reference_tests=True,
    )
    manifest = _manifest_payload(dataset_path)
    _ensure_manifest(manifest_path, results_path, manifest)

    if run_preflight:
        preflight, quality_preflight = run_benchmark_preflight()
        print(
            "RAG ablation preflight passed "
            f"(coverage={preflight.coverage or 0.0:.1f}%, "
            f"score={quality_preflight.final_score:.1f}).",
            flush=True,
        )

    from core.generator import generate_with_reflection

    cfg = get_config()
    cfg["llm"]["model"] = MODEL_ID
    clear_llm_cache()

    results_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not results_path.exists() or results_path.stat().st_size == 0
    completed = _existing_keys(results_path)
    jsonl_path = results_path.with_suffix(".jsonl")
    artifacts_root = results_path.with_suffix("").with_name(
        f"{results_path.stem}_artifacts"
    )

    selected = list(_selected_runs(records, condition))
    with results_path.open("a", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=ABLATION_RESULT_COLUMNS)
        if is_new:
            writer.writeheader()
            csv_file.flush()

        for run_index, (_task_index, record, rag_enabled) in enumerate(selected, 1):
            condition_name = "RAG_ON" if rag_enabled else "RAG_OFF"
            project_hash = _project_hash(record)
            resume_key = (
                condition_name,
                str(record["task_id"]),
                project_hash,
                EVALUATOR_VERSION,
            )
            if resume_key in completed:
                print(
                    f"[{run_index}/{len(selected)}] {record['task_id']} "
                    f"{condition_name}: already complete; skipping.",
                    flush=True,
                )
                continue

            print(
                f"[{run_index}/{len(selected)}] {record['task_id']} "
                f"{condition_name}: generating...",
                flush=True,
            )
            started = time.time()
            attempts = 0
            last_status = ""
            final_result: dict[str, Any] = {}
            first_result: dict[str, Any] = {}
            final_test_code = ""
            project_files = dict(record["project_files"])

            try:
                for status, code, result in generate_with_reflection(
                    file_name=record["target_file"],
                    source_code=record["target_source"],
                    max_retries=MAX_RETRIES,
                    target_coverage=DEFAULT_MINIMUM_COVERAGE,
                    rag_enabled=rag_enabled,
                    project_files=project_files,
                    project_context_k=PROJECT_CONTEXT_K,
                    rag_strict=rag_enabled,
                ):
                    if status != last_status:
                        if "Attempt" in status and "Generating code" in status:
                            attempts += 1
                        last_status = status
                    if isinstance(code, str) and code.strip():
                        final_test_code = code
                    if isinstance(result, dict) and result.get("execution_status"):
                        final_result = dict(result)
                        if not first_result:
                            first_result = dict(result)
            except SandboxInfrastructureError:
                raise
            except Exception as exc:
                raise RuntimeError(
                    f"RAG ablation generation failed for {record['task_id']} "
                    f"{condition_name}: {exc}"
                ) from exc

            generation_time = time.time() - started
            metrics = evaluate_result(
                final_result,
                attempts=attempts,
                minimum_coverage=DEFAULT_MINIMUM_COVERAGE,
            )
            attempts = metrics["attempts"]
            artifact_dir = (
                artifacts_root
                / condition_name.lower()
                / str(record["task_id"])
            )
            evaluation = evaluate_python_test(
                file_name=record["target_file"],
                source_code=record["target_source"],
                test_code=final_test_code,
                project_files=project_files,
                artifact_dir=artifact_dir,
            )
            context_error, context_category = _context_error(first_result)
            base_row = _result_row(
                model_id=MODEL_ID,
                task_id=record["task_id"],
                evaluation=evaluation,
                generation_metrics=metrics,
                attempts=attempts,
                generation_time=generation_time,
            )
            row = {
                "AblationSchemaVersion": ABLATION_SCHEMA_VERSION,
                "Condition": condition_name,
                "RAGEnabled": rag_enabled,
                "ProjectContextK": PROJECT_CONTEXT_K if rag_enabled else 0,
                "FewshotCandidateK": FEWSHOT_CANDIDATE_K if rag_enabled else 0,
                "Category": record["category"],
                "ProjectHash": project_hash,
                "RequiredSymbols": _required_symbols(record),
                "FirstAttemptExecutionStatus": first_result.get(
                    "execution_status", "no_generated_test"
                ),
                "FirstAttemptCompileCollectionPassed": (
                    _compile_collection_passed(first_result)
                ),
                "FirstAttemptTestsPassed": bool(first_result.get("success", False)),
                "FirstAttemptCoverage": first_result.get("coverage", ""),
                "FirstAttemptContextError": context_error,
                "FirstAttemptContextErrorCategory": context_category,
                **base_row,
            }
            writer.writerow(row)
            csv_file.flush()
            _write_jsonl(
                jsonl_path,
                record=record,
                condition=condition_name,
                project_hash=project_hash,
                first_result=first_result,
                generation_metrics=metrics,
                evaluation=evaluation,
            )
            completed.add(resume_key)
            print(
                f"  {record['task_id']} {condition_name}: "
                f"accepted={metrics['accepted']}, status={evaluation.status}, "
                f"line={evaluation.coverage.line_percent or 0.0:.1f}%, "
                f"score={evaluation.final_score if evaluation.final_score is not None else 'incomplete'}",
                flush=True,
            )

    try:
        unload_ollama_model(
            MODEL_ID,
            cfg.get("llm", {}).get("base_url", "http://localhost:11434"),
        )
    except (OllamaUnloadError, requests.RequestException) as exc:
        raise RuntimeError(
            f"RAG ablation completed but model unload could not be verified: {exc}"
        ) from exc

    expected_keys = {
        (
            "RAG_ON" if rag_enabled else "RAG_OFF",
            str(record["task_id"]),
            _project_hash(record),
            EVALUATOR_VERSION,
        )
        for _task_index, record, rag_enabled in selected
    }
    expected = len(expected_keys)
    finished = len(expected_keys.intersection(completed))
    print(
        f"RAG ablation condition={condition} complete: {finished}/{expected} rows. "
        f"Results: {results_path}",
        flush=True,
    )
    complete = expected_keys.issubset(completed)
    if complete and condition == "both":
        from .compare_results import generate_comparison

        table_path = results_path.with_name("rag_ablation_table.tex")
        generate_comparison(results_path, table_path)
        print(f"RAG ablation LaTeX table: {table_path}", flush=True)
    return complete


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--embedded-dataset", type=Path, default=DEFAULT_EMBEDDED_DATASET
    )
    parser.add_argument("--results-path", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--condition", choices=("both", "rag", "no-rag"), default="both"
    )
    parser.add_argument("--skip-preflight", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        completed = run_ablation(
            dataset_path=args.dataset,
            embedded_dataset_path=args.embedded_dataset,
            results_path=args.results_path,
            manifest_path=args.manifest_path,
            condition=args.condition,
            run_preflight=not args.skip_preflight,
        )
    except (SandboxInfrastructureError, RuntimeError, ValueError) as exc:
        print(f"RAG ablation aborted: {exc}", flush=True)
        return 1
    return 0 if completed else 1


if __name__ == "__main__":
    raise SystemExit(main())
