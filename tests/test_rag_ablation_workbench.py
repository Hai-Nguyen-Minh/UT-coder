import csv
import json
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

from core.benchmark import evaluate_models
from core.benchmark.evaluation_schema import EVALUATOR_VERSION
from core.benchmark.rag_ablation import compare_results
from core.benchmark.rag_ablation import evaluate_rag_ablation as workbench
from core.benchmark.rag_ablation.validate_dataset import (
    DEFAULT_DATASET,
    DEFAULT_EMBEDDED_DATASET,
    EXPECTED_CATEGORIES,
    validate_dataset,
)
import core.llm as llm_module


def test_dataset_has_twenty_balanced_project_tasks():
    records = validate_dataset(
        DEFAULT_DATASET,
        DEFAULT_EMBEDDED_DATASET,
        run_reference_tests=False,
    )

    assert len(records) == 20
    assert len({record["task_id"] for record in records}) == 20
    assert len({record["target_file"] for record in records}) == 20
    assert Counter(record["category"] for record in records) == Counter(
        {category: 4 for category in EXPECTED_CATEGORIES}
    )
    assert all(record["project_files"] for record in records)
    assert all(record["required_symbols"] for record in records)


def test_both_condition_is_paired_and_counterbalanced():
    records = [{"task_id": f"task_{index}"} for index in range(4)]

    selected = list(workbench._selected_runs(records, "both"))

    assert len(selected) == 8
    for index in range(4):
        pair = selected[index * 2 : index * 2 + 2]
        assert [item[1]["task_id"] for item in pair] == [
            f"task_{index}",
            f"task_{index}",
        ]
        assert [item[2] for item in pair] == (
            [False, True] if index % 2 == 0 else [True, False]
        )

    assert [enabled for _, _, enabled in workbench._selected_runs(records, "rag")] == [
        True
    ] * 4
    assert [
        enabled for _, _, enabled in workbench._selected_runs(records, "no-rag")
    ] == [False] * 4


@pytest.mark.parametrize(
    ("first_result", "expected"),
    [
        (
            {
                "execution_status": "collection_error",
                "stderr": "ImportError: cannot import name 'Order' from 'domain'",
            },
            (True, "internal_import"),
        ),
        (
            {
                "execution_status": "tests_failed",
                "error_log": "AttributeError: 'Repository' object has no attribute 'fetch'",
            },
            (True, "missing_symbol"),
        ),
        (
            {
                "execution_status": "tests_failed",
                "stderr": "TypeError: InvoiceItem.__init__() missing 1 required positional argument",
            },
            (True, "signature_or_constructor"),
        ),
        (
            {
                "execution_status": "tests_failed",
                "stderr": "TypeError: object MagicMock cannot be used in 'await' expression",
            },
            (True, "async_or_protocol_contract"),
        ),
        (
            {
                "execution_status": "test_compile_error",
                "stderr": "NameError: name 'Order' is not defined",
            },
            (False, ""),
        ),
        (
            {
                "execution_status": "tests_failed",
                "stderr": "AssertionError: assert 1 == 2",
            },
            (False, ""),
        ),
    ],
)
def test_first_attempt_context_error_classifier(first_result, expected):
    assert workbench._context_error(first_result) == expected


@pytest.mark.parametrize(
    ("first_result", "expected"),
    [
        ({"execution_status": "tests_passed", "tests_collected": 3}, True),
        ({"execution_status": "tests_failed", "tests_collected": 2}, True),
        ({"execution_status": "collection_error", "tests_collected": 0}, False),
        ({"execution_status": "no_tests_collected", "tests_collected": 0}, False),
        ({"execution_status": "tests_passed", "tests_collected": None}, False),
    ],
)
def test_compile_collection_metric_requires_collected_tests(first_result, expected):
    assert workbench._compile_collection_passed(first_result) is expected


def _write_paired_results(path: Path, *, mismatched_hash: bool = False) -> None:
    rows = []
    for index in range(20):
        task_id = f"rag_ctx_{index + 1:02d}"
        for condition in ("RAG_OFF", "RAG_ON"):
            project_hash = f"hash-{index}"
            if mismatched_hash and index == 0 and condition == "RAG_ON":
                project_hash = "different-hash"
            rows.append(
                {
                    "Condition": condition,
                    "TaskID": task_id,
                    "ProjectHash": project_hash,
                    "FirstAttemptCompileCollectionPassed": condition == "RAG_ON",
                    "FirstAttemptContextError": condition == "RAG_OFF",
                    "EventualAccepted": condition == "RAG_ON",
                    "ScoreComplete": True,
                    "FinalScore": 80 if condition == "RAG_ON" else 40,
                }
            )
    pd.DataFrame(rows).to_csv(path, index=False)


def test_comparator_requires_and_summarizes_twenty_paired_tasks(tmp_path):
    results = tmp_path / "results.csv"
    output = tmp_path / "table.tex"
    _write_paired_results(results)

    summary = compare_results.generate_comparison(results, output)

    by_condition = summary.set_index("Condition")
    assert by_condition.loc["RAG_OFF", "Tasks"] == 20
    assert by_condition.loc["RAG_ON", "Tasks"] == 20
    assert by_condition.loc["RAG_OFF", "ContextErrorFirst_pct"] == 100.0
    assert by_condition.loc["RAG_ON", "CompileCollectionFirst_pct"] == 100.0
    assert by_condition.loc["RAG_ON", "FinalScore_mean_pct"] == 80.0
    assert output.is_file()
    assert output.with_suffix(".csv").is_file()
    latex = output.read_text(encoding="utf-8")
    assert "Không RAG" in latex
    assert "Có RAG" in latex


def test_comparator_rejects_project_hash_mismatch(tmp_path):
    results = tmp_path / "results.csv"
    _write_paired_results(results, mismatched_hash=True)

    with pytest.raises(ValueError, match="different project hashes"):
        compare_results.generate_comparison(results, tmp_path / "table.tex")


def test_manifest_and_resume_key_preserve_provenance(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    results_path = tmp_path / "results.csv"
    expected = {"dataset_sha256": "dataset-v1", "model": workbench.MODEL_ID}

    workbench._ensure_manifest(manifest_path, results_path, expected)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert {key: manifest[key] for key in expected} == expected
    assert manifest["created_at_utc"]

    row = {column: "" for column in workbench.ABLATION_RESULT_COLUMNS}
    row.update(
        {
            "Condition": "RAG_ON",
            "Model": workbench.MODEL_ID,
            "TaskID": "rag_ctx_01",
            "ProjectHash": "project-hash",
            "EvaluatorVersion": EVALUATOR_VERSION,
        }
    )
    with results_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=workbench.ABLATION_RESULT_COLUMNS)
        writer.writeheader()
        writer.writerow(row)

    assert workbench._existing_keys(results_path) == {
        ("RAG_ON", "rag_ctx_01", "project-hash", EVALUATOR_VERSION)
    }
    with pytest.raises(ValueError, match="Changed: dataset_sha256"):
        workbench._ensure_manifest(
            manifest_path,
            results_path,
            {"dataset_sha256": "dataset-v2", "model": workbench.MODEL_ID},
        )


def test_nonempty_results_without_manifest_are_rejected(tmp_path):
    results_path = tmp_path / "results.csv"
    results_path.write_text("Condition,TaskID\nRAG_ON,task\n", encoding="utf-8")

    with pytest.raises(ValueError, match="without its provenance manifest"):
        workbench._ensure_manifest(
            tmp_path / "missing-manifest.json",
            results_path,
            {"dataset_sha256": "dataset-v1"},
        )


def test_llm_client_is_cached_until_explicitly_cleared(monkeypatch):
    created = []
    config = {
        "llm": {
            "base_url": "http://ollama:11434",
            "model": "llama3.1:8b",
            "temperature": 0.1,
        }
    }

    def fake_chat_ollama(**kwargs):
        client = {"sequence": len(created), **kwargs}
        created.append(client)
        return client

    monkeypatch.setattr(llm_module, "ChatOllama", fake_chat_ollama)
    monkeypatch.setattr(llm_module, "get_config", lambda: config)
    llm_module.clear_llm_cache()

    first = llm_module.get_llm()
    assert llm_module.get_llm() is first
    assert len(created) == 1

    config["llm"]["model"] = "qwen2.5-coder:7b"
    llm_module.clear_llm_cache()
    second = llm_module.get_llm()
    assert second is not first
    assert second["model"] == "qwen2.5-coder:7b"
    assert len(created) == 2

    llm_module.clear_llm_cache()


def test_main_benchmark_chains_rag_by_default_and_exposes_opt_out():
    default_args = evaluate_models._parse_args([])
    skipped_args = evaluate_models._parse_args(["--skip-rag-ablation"])
    repair_args = evaluate_models._parse_args(["--rerun-failed-from", "failed.csv"])

    assert default_args.skip_rag_ablation is False
    assert skipped_args.skip_rag_ablation is True
    assert repair_args.rerun_failed_from == "failed.csv"

