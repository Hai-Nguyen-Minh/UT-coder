import argparse
import os
import json
import time
import csv
import datetime
import requests
import re
from pathlib import Path

# Adjust sys.path so we can import from core
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from core.config import get_config
from core.benchmark.metrics import DEFAULT_MINIMUM_COVERAGE, evaluate_result
from core.benchmark.evaluation_schema import (
    EVALUATOR_VERSION,
    SCHEMA_VERSION,
    EvaluationResult,
    EvaluationStatus,
    content_hash,
)
from core.benchmark.failed_selection import load_failed_pairs
from core.ollama_memory import OllamaUnloadError, unload_ollama_model
from core.sandbox.base import SandboxInfrastructureError
from core.sandbox.preflight import run_benchmark_preflight
from core.sandbox.internal.eval_runner import (
    evaluate_python_test,
)

# Progress log file — relative path works both on server (/app/) and local
PROGRESS_LOG = os.path.join(os.path.dirname(__file__), "benchmark_progress.log")
progress_history = []
MAX_TASKS_PER_MODEL = 50
MINIMUM_COVERAGE = DEFAULT_MINIMUM_COVERAGE
RESULT_COLUMNS = [
    "SchemaVersion", "EvaluatorVersion", "Model", "TaskID",
    "SourceHash", "TestHash",
    "FirstAttemptAccepted", "EventualAccepted", "AcceptedAtAttempt",
    "EvaluationStatus", "Valid", "ScoreComplete", "Stable",
    "Collected", "Passed", "Failed", "Errors", "Skipped", "XFailed", "XPassed",
    "StabilityPassedRuns", "StabilityMultiplier",
    "Coverage", "LineCoverage", "BranchCoverage",
    "MutantsKilled", "MutantsTimedOut", "MutantsSegfault",
    "MutantsSurvived", "MutantsNoTests", "MutantsExcluded",
    "MutantsApplicable", "MutationScore", "MutationWeightsNormalized",
    "BaseScore", "FinalScore", "QualityBand",
    "Attempts", "GenerationTime_s", "EvaluationTime_s", "TimeTaken_s",
]


def _safe_artifact_component(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("._") or "unknown"


def _result_row(
    *,
    model_id,
    task_id,
    evaluation,
    generation_metrics,
    attempts,
    generation_time,
):
    collection = evaluation.collection
    representative = evaluation.coverage_run
    if not representative.report_valid and evaluation.stability_runs:
        representative = next(
            (run for run in evaluation.stability_runs if run.successful),
            evaluation.stability_runs[-1],
        )
    mutation = evaluation.mutation
    accepted_at = attempts if generation_metrics.get("accepted") else ""
    line_coverage = evaluation.coverage.line_percent
    return {
        "SchemaVersion": SCHEMA_VERSION,
        "EvaluatorVersion": EVALUATOR_VERSION,
        "Model": model_id,
        "TaskID": task_id,
        "SourceHash": evaluation.source_hash,
        "TestHash": evaluation.test_hash,
        "FirstAttemptAccepted": generation_metrics.get("pass_at_1", False),
        "EventualAccepted": generation_metrics.get("accepted", False),
        "AcceptedAtAttempt": accepted_at,
        "EvaluationStatus": evaluation.status,
        "Valid": evaluation.valid,
        "ScoreComplete": evaluation.score_complete,
        "Stable": evaluation.stable,
        "Collected": collection.collected,
        "Passed": representative.passed,
        "Failed": representative.failed,
        "Errors": representative.errors,
        "Skipped": representative.skipped,
        "XFailed": representative.xfailed,
        "XPassed": representative.xpassed,
        "StabilityPassedRuns": evaluation.stability_passed_runs,
        "StabilityMultiplier": evaluation.stability_multiplier,
        # Coverage is retained as a v1 compatibility alias for line coverage.
        "Coverage": "" if line_coverage is None else line_coverage,
        "LineCoverage": "" if line_coverage is None else line_coverage,
        "BranchCoverage": (
            "" if evaluation.coverage.branch_percent is None
            else evaluation.coverage.branch_percent
        ),
        "MutantsKilled": mutation.killed,
        "MutantsTimedOut": mutation.timed_out,
        "MutantsSegfault": mutation.segfault,
        "MutantsSurvived": mutation.survived,
        "MutantsNoTests": mutation.no_tests,
        "MutantsExcluded": mutation.excluded,
        "MutantsApplicable": mutation.applicable,
        "MutationScore": "" if mutation.score_percent is None else mutation.score_percent,
        "MutationWeightsNormalized": evaluation.mutation_weights_normalized,
        "BaseScore": "" if evaluation.base_score is None else evaluation.base_score,
        "FinalScore": "" if evaluation.final_score is None else evaluation.final_score,
        "QualityBand": evaluation.band,
        "Attempts": max(1, int(attempts or 0)),
        "GenerationTime_s": round(generation_time, 2),
        "EvaluationTime_s": round(evaluation.duration_seconds, 2),
        "TimeTaken_s": round(generation_time + evaluation.duration_seconds, 2),
    }


def _write_jsonl(path, *, model_id, task_id, generation_metrics, evaluation):
    payload = {
        "model": model_id,
        "task_id": task_id,
        "generation": generation_metrics,
        "evaluation": evaluation.to_dict(),
    }
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def fmt_time(seconds):
    """Format seconds into human-readable string."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h{m:02d}m{s:02d}s"
    return f"{m}m{s:02d}s"


def log_progress(msg):
    """Print to stdout AND append to progress log file."""
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(PROGRESS_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def write_progress_summary(model_id, current_idx, total_len, elapsed, current_log=None):
    """Overwrite a summary block at the top of the log for quick status checks."""
    pct = int((current_idx / total_len) * 100) if total_len > 0 else 0
    bar_filled = int(pct / 5)
    bar = "█" * bar_filled + "░" * (20 - bar_filled)

    # Estimate remaining time
    if current_idx > 0:
        avg_per_task = elapsed / current_idx
        remaining = avg_per_task * (total_len - current_idx)
        eta = f"~{fmt_time(remaining)}"
    else:
        eta = "calculating..."

    summary = []
    summary.append("=" * 60)
    summary.append(f"  BENCHMARK PROGRESS: {model_id}")
    summary.append(f"  [{bar}] {pct}% ({current_idx}/{total_len})")
    summary.append(f"  Elapsed: {fmt_time(elapsed)}  |  ETA: {eta}")
    if current_log:
        summary.append(f"  Status: {current_log}")
    summary.append("=" * 60)

    # Write summary file (separate from append log)
    try:
        summary_path = os.path.join(os.path.dirname(__file__), "benchmark_status.txt")
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("\n".join(summary) + "\n\n")
            f.write("Recent history:\n")
            for h in progress_history[:15]:
                f.write(f"  {h}\n")
    except Exception:
        pass


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate local Ollama models.")
    parser.add_argument(
        "--rerun-failed-from",
        metavar="CSV",
        help=(
            "Run only failed Model+TaskID pairs. Supports legacy Pass_at_3/"
            "coverage CSVs and current invalid/incomplete CSVs."
        ),
    )
    parser.add_argument(
        "--results-path",
        metavar="CSV",
        help="Output CSV. Failed-only mode defaults to <input>_rerun_failed.csv.",
    )
    parser.add_argument(
        "--skip-rag-ablation",
        action="store_true",
        help=(
            "Finish the two-model benchmark without automatically running the "
            "paired 20-task RAG ablation."
        ),
    )
    return parser.parse_args(argv)


def _failed_output_path(source_path):
    source = Path(source_path)
    return str(source.with_name(f"{source.stem}_rerun_failed.csv"))


def main(argv=None):
    args = _parse_args(argv)
    dataset_path = "core/benchmark/eval_dataset.json"
    results_path = args.results_path or (
        _failed_output_path(args.rerun_failed_from)
        if args.rerun_failed_from
        else "core/benchmark/benchmark_results.csv"
    )
    if (
        args.rerun_failed_from
        and Path(results_path).resolve() == Path(args.rerun_failed_from).resolve()
    ):
        raise ValueError("Failed-only output must not overwrite the source results CSV.")

    if not os.path.exists(dataset_path):
        print(f"Error: Dataset {dataset_path} not found. Run eval_sampler.py first.")
        return

    with open(dataset_path, 'r', encoding='utf-8') as f:
        dataset = json.load(f)

    # The final 20 tasks can be appended without another code change.
    dataset = dataset[:MAX_TASKS_PER_MODEL]

    log_progress(
        f"Loaded {len(dataset)} snippets from dataset "
        f"(capacity={MAX_TASKS_PER_MODEL} per model)."
    )
    if len(dataset) < MAX_TASKS_PER_MODEL:
        log_progress(
            f"Dataset is currently {len(dataset)}/{MAX_TASKS_PER_MODEL}; "
            f"waiting for {MAX_TASKS_PER_MODEL - len(dataset)} additional task(s)."
        )

    cfg = get_config()
    all_models = [m["id"] for m in cfg.get("llm", {}).get("available_models", [])]
    # Evaluate the two requested local AI models in configured order.
    models_to_eval = [m for m in all_models if m in ("llama3.1:8b", "qwen2.5-coder:7b")]

    if not models_to_eval:
        log_progress("ERROR: Required models not found in config.")
        return

    log_progress(f"Models to evaluate: {models_to_eval}")

    selected_pairs = None
    if args.rerun_failed_from:
        failed_pairs = load_failed_pairs(
            args.rerun_failed_from,
            minimum_coverage=MINIMUM_COVERAGE,
        )
        dataset_ids = {str(item["task_id"]) for item in dataset}
        selected_pairs = {
            (model, task_id)
            for model, task_id in failed_pairs
            if model in models_to_eval and task_id in dataset_ids
        }
        omitted = failed_pairs - selected_pairs
        if omitted:
            log_progress(
                f"Ignored {len(omitted)} failed pair(s) not present in the current "
                "50-task dataset/model configuration."
            )
        if not selected_pairs:
            log_progress("No failed model-task pairs matched the current benchmark.")
            return
        models_to_eval = [
            model for model in models_to_eval
            if any(pair[0] == model for pair in selected_pairs)
        ]
        log_progress(
            f"Failed-only mode selected {len(selected_pairs)} model-task run(s) "
            f"from {args.rerun_failed_from}."
        )
        log_progress(f"Failed-only results will be written to {results_path}.")

    try:
        preflight, quality_preflight = run_benchmark_preflight()
        log_progress(
            f"Sandbox preflight passed (coverage={preflight.coverage or 0.0:.1f}%)."
        )
        log_progress(
            "Evaluator preflight passed "
            f"(score={quality_preflight.final_score:.1f}, "
            f"mutants={quality_preflight.mutation.applicable})."
        )
    except SandboxInfrastructureError as e:
        log_progress(f"🛑 BENCHMARK NOT STARTED — sandbox preflight failed: {e}")
        return
    except Exception as e:
        log_progress(f"BENCHMARK NOT STARTED — evaluator preflight failed: {e}")
        return

    # Import the heavy RAG/generation stack only after CLI parsing and the
    # deterministic sandbox preflight have succeeded.
    from core.generator import generate_with_reflection

    # Clear old progress log
    try:
        open(PROGRESS_LOG, "w").close()
    except Exception:
        pass

    # Prepare CSV writer
    Path(results_path).parent.mkdir(parents=True, exist_ok=True)
    is_new = not os.path.exists(results_path) or os.path.getsize(results_path) == 0
    if not is_new:
        with open(results_path, "r", encoding="utf-8-sig", newline="") as existing:
            fieldnames = csv.DictReader(existing).fieldnames or []
        missing = set(RESULT_COLUMNS) - set(fieldnames)
        if missing:
            raise ValueError(
                "The output CSV uses an old schema; archive it or choose a new path. "
                f"Missing columns: {', '.join(sorted(missing))}"
            )
    csv_file = open(results_path, 'a', newline='', encoding='utf-8')
    csv_writer = csv.DictWriter(csv_file, fieldnames=RESULT_COLUMNS)
    if is_new:
        csv_writer.writeheader()
        csv_file.flush()
    jsonl_path = str(Path(results_path).with_suffix(".jsonl"))
    artifacts_root = Path(results_path).with_suffix("").with_name(
        f"{Path(results_path).stem}_artifacts"
    )

    # Total samples across all models
    total_evals = (
        len(selected_pairs)
        if selected_pairs is not None
        else len(models_to_eval) * len(dataset)
    )
    global_start = time.time()
    completed = 0

    for model_id in models_to_eval:
        log_progress(f"\n{'=' * 60}")
        log_progress(f"  START MODEL: {model_id}")
        log_progress(f"{'=' * 60}")

        # Override the model in the config so core/llm.py picks it up
        cfg["llm"]["model"] = model_id
        # get_llm() is cached for normal API traffic. A benchmark process
        # changes model IDs in-place, so it must invalidate that client before
        # generating the first task for the next model.
        from core.llm import clear_llm_cache
        clear_llm_cache()
        # Get already completed tasks for this model to support resuming
        completed_tasks_for_model = set()
        if os.path.exists(results_path):
            with open(results_path, 'r', encoding='utf-8-sig', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if (
                        row.get("Model") == model_id
                        and row.get("EvaluatorVersion") == EVALUATOR_VERSION
                    ):
                        completed_tasks_for_model.add(
                            (row.get("TaskID", ""), row.get("SourceHash", ""))
                        )

        model_dataset = [
            item for item in dataset
            if selected_pairs is None
            or (model_id, str(item["task_id"])) in selected_pairs
        ]
        for idx, item in enumerate(model_dataset):
            task_id = item["task_id"]
            source_code = item["source_code"]

            if (str(task_id), content_hash(source_code)) in completed_tasks_for_model:
                log_progress(f"[{model_id}] ({idx+1}/{len(model_dataset)}) Task {task_id} — Skipping (already in CSV)...")
                completed += 1
                continue

            elapsed = time.time() - global_start
            write_progress_summary(model_id, completed, total_evals, elapsed)
            log_progress(f"[{model_id}] ({idx+1}/{len(model_dataset)}) Task {task_id} — Starting...")

            # Write a temporary python file
            tmp_filename = f"task_{task_id}.py"
            with open(tmp_filename, "w", encoding="utf-8") as f:
                f.write(source_code)

            start_time = time.time()
            final_result = None
            final_test_code = ""
            attempts = 0

            # Run generator with reflection
            last_status = ""
            try:
                for status_msg, code_so_far, result_obj in generate_with_reflection(
                    file_name=tmp_filename,
                    source_code=source_code,
                    target_coverage=MINIMUM_COVERAGE,
                    max_retries=3
                ):
                    final_result = result_obj
                    if isinstance(code_so_far, str) and code_so_far.strip():
                        final_test_code = code_so_far

                    # Only log when the status message ACTUALLY changes
                    if status_msg != last_status:
                        if "Attempt" in status_msg and "Generating code" in status_msg:
                            attempts += 1
                        last_status = status_msg
                        log_progress(f"  [{model_id}] Task {task_id}: {status_msg}")
                    write_progress_summary(model_id, completed, total_evals,
                                           time.time() - global_start, current_log=status_msg)

                generation_time = time.time() - start_time
                metrics = evaluate_result(
                    final_result or {},
                    attempts=attempts,
                    minimum_coverage=MINIMUM_COVERAGE,
                )
                attempts = metrics["attempts"]
                artifact_dir = (
                    artifacts_root
                    / _safe_artifact_component(model_id)
                    / _safe_artifact_component(task_id)
                )
                try:
                    evaluation = evaluate_python_test(
                        file_name=tmp_filename,
                        source_code=source_code,
                        test_code=final_test_code,
                        artifact_dir=artifact_dir,
                    )
                except Exception as exc:
                    raise SandboxInfrastructureError(
                        f"Evaluator crashed unexpectedly: {exc}"
                    ) from exc

                csv_writer.writerow(_result_row(
                    model_id=model_id,
                    task_id=task_id,
                    evaluation=evaluation,
                    generation_metrics=metrics,
                    attempts=attempts,
                    generation_time=generation_time,
                ))
                csv_file.flush()
                _write_jsonl(
                    jsonl_path,
                    model_id=model_id,
                    task_id=task_id,
                    generation_metrics=metrics,
                    evaluation=evaluation,
                )

                mutation_display = (
                    "n/a"
                    if evaluation.mutation.score_percent is None
                    else f"{evaluation.mutation.score_percent:.1f}%"
                )
                score_display = (
                    "incomplete"
                    if evaluation.final_score is None
                    else f"{evaluation.final_score:.1f}"
                )
                icon = "✅" if evaluation.valid and evaluation.score_complete else "❌"
                result_line = (
                    f"{icon} [{model_id}] Task {task_id} — "
                    f"Status={evaluation.status}, Score={score_display}, "
                    f"Line={evaluation.coverage.line_percent or 0.0:.1f}%, "
                    f"Branch={evaluation.coverage.branch_percent or 0.0:.1f}%, "
                    f"Mutation={mutation_display}, Stability="
                    f"{evaluation.stability_passed_runs}/3, "
                    f"Generation={fmt_time(generation_time)}, "
                    f"Evaluation={fmt_time(evaluation.duration_seconds)}"
                )
                log_progress(result_line)
                progress_history.insert(0, result_line)
                if len(progress_history) > 15:
                    progress_history.pop()

            except SandboxInfrastructureError as e:
                time_taken = time.time() - start_time
                err_line = (
                    f"🛑 BENCHMARK ABORTED [{model_id}] Task {task_id} — "
                    f"sandbox infrastructure failure: {e}, Time={fmt_time(time_taken)}"
                )
                log_progress(err_line)
                progress_history.insert(0, err_line)

                # Infrastructure failures must not be recorded as model
                # failures. Stop immediately instead of wasting all retries
                # and contaminating Pass@k metrics.
                if os.path.exists(tmp_filename):
                    os.remove(tmp_filename)
                csv_file.close()
                write_progress_summary(
                    model_id,
                    completed,
                    total_evals,
                    time.time() - global_start,
                    current_log="ABORTED: fix/rebuild the Ubuntu sandbox image",
                )
                return

            except Exception as e:
                generation_time = time.time() - start_time
                err_line = f"💥 [{model_id}] Task {task_id} — Exception: {e}, Time={fmt_time(generation_time)}"
                log_progress(err_line)
                progress_history.insert(0, err_line)
                metrics = evaluate_result(
                    {}, attempts=attempts, minimum_coverage=MINIMUM_COVERAGE
                )
                evaluation = EvaluationResult.empty(
                    EvaluationStatus.NO_GENERATED_TEST,
                    source_code=source_code,
                    test_code=final_test_code,
                    diagnostic=str(e),
                )
                evaluation.finalize_invalid_score()
                csv_writer.writerow(_result_row(
                    model_id=model_id,
                    task_id=task_id,
                    evaluation=evaluation,
                    generation_metrics=metrics,
                    attempts=attempts,
                    generation_time=generation_time,
                ))
                csv_file.flush()

            # Clean up
            if os.path.exists(tmp_filename):
                os.remove(tmp_filename)

            completed += 1

            # End-of-task summary
            elapsed = time.time() - global_start
            write_progress_summary(model_id, completed, total_evals, elapsed)

        # Ollama runs on the local GPU machine through the configured tunnel.
        # Confirm release before starting the next AI.
        try:
            log_progress(f"Unloading model {model_id} from Ollama memory...")
            unload_ollama_model(
                model_id,
                cfg.get("llm", {}).get("base_url", "http://localhost:11434"),
            )
            log_progress(
                f"Model {model_id} is no longer listed by Ollama; "
                "RAM/VRAM released."
            )
        except (OllamaUnloadError, requests.RequestException) as e:
            log_progress(
                f"BENCHMARK ABORTED — could not verify unload for {model_id}: {e}"
            )
            csv_file.close()
            return

    csv_file.close()
    total_time = time.time() - global_start
    log_progress(f"\n{'=' * 60}")
    log_progress(f"  BENCHMARK COMPLETED in {fmt_time(total_time)}")
    log_progress(f"  Results saved to: {results_path}")
    log_progress(f"{'=' * 60}")

    # A failed-only repair run must stay narrowly scoped. A normal full/resume
    # run chains into the separate project-aware RAG workbench only after both
    # model loops and their verified unloads completed successfully.
    if args.rerun_failed_from:
        log_progress("RAG ablation not chained from failed-only benchmark mode.")
    elif args.skip_rag_ablation:
        log_progress("RAG ablation skipped by --skip-rag-ablation.")
    else:
        log_progress("Starting paired 20-task RAG ablation with Qwen...")
        from core.benchmark.rag_ablation.evaluate_rag_ablation import run_ablation

        try:
            rag_complete = run_ablation()
        except Exception as exc:
            log_progress(
                "RAG ablation aborted after the main benchmark completed: "
                f"{exc}"
            )
            return
        if not rag_complete:
            log_progress("RAG ablation did not produce all expected paired rows.")
            return
        log_progress("RAG ablation completed successfully.")


if __name__ == "__main__":
    main()
