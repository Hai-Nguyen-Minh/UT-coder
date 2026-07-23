import ast

from core.dataset.embed_rag import get_semantic_description
from core.dataset.prepare_rag_dataset import prepare_dataset, prepare_row


def _row(task_id, source, tests, coverage=100.0):
    return {
        "task_id": task_id,
        "source": source,
        "tests": tests,
        "coverage": coverage,
        "status": "valid",
    }


def test_duplicate_task_ids_receive_unique_content_ids():
    rows = [
        _row(1, "def first():\n    return 1\n", "import unittest\nfrom module_under_test import *\nclass T(unittest.TestCase):\n def test_x(self): self.assertEqual(first(), 1)\n"),
        _row(1, "def second():\n    return 2\n", "import unittest\nfrom module_under_test import *\nclass T(unittest.TestCase):\n def test_x(self): self.assertEqual(second(), 2)\n"),
    ]

    prepared, stats = prepare_dataset(rows)

    assert stats["unique_dataset_ids"] == 2
    assert prepared[0]["dataset_id"] != prepared[1]["dataset_id"]


def test_ground_truth_is_preserved_and_rag_test_is_pytest_style():
    tests = "import unittest\nfrom module_under_test import *\nclass T(unittest.TestCase):\n def test_x(self): self.assertEqual(add(1, 2), 3)\n"
    prepared = prepare_row(_row(2, "def add(a, b):\n    return a + b\n", tests))

    assert prepared["tests"] == tests
    assert prepared["rag_eligible"] is True
    assert "import pytest" in prepared["rag_tests"]
    assert "self.assert" not in prepared["rag_tests"]
    assert "import *" not in prepared["rag_tests"]
    ast.parse(prepared["rag_tests"])


def test_quality_gate_rejects_low_coverage_and_no_assertion():
    low_coverage = prepare_row(_row(3, "def f():\n return 1\n", "def test_f():\n assert f() == 1\n", 90.0))
    no_assertion = prepare_row(_row(4, "def f():\n return 1\n", "def test_f():\n f()\n"))

    assert low_coverage["rag_eligible"] is False
    assert "coverage_below_100" in low_coverage["rag_quality_reasons"]
    assert no_assertion["rag_eligible"] is False
    assert "no_assertion" in no_assertion["rag_quality_reasons"]


def test_semantic_description_contains_behavioral_structure():
    description = get_semantic_description(
        "def divide(a: int, b: int):\n    if b == 0:\n        raise ValueError('zero')\n    return a / b\n"
    )

    assert "branches b == 0" in description
    assert "raises ValueError" in description
