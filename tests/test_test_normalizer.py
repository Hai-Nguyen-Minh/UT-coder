import ast

from core.test_normalizer import normalize_python_tests


def test_normalizer_removes_nested_import_and_converts_unittest_assertions():
    source = '''
def public(value):
    def inner():
        return 1
    return value + inner()
'''
    generated = '''
from invented_module import public, inner

class TestPublic:
    def test_value(self):
        self.assertEqual(public(2), 3, "message")

    def test_truth(self):
        self.assertTrue(public(0))
'''

    normalized = normalize_python_tests(generated, source)
    ast.parse(normalized)

    assert "from module_under_test import public" in normalized
    assert "inner" not in normalized
    assert "self.assert" not in normalized
    assert "assert public(2) == 3" in normalized
    assert "assert public(0)" in normalized


def test_normalizer_preserves_dependency_imported_by_source():
    source = '''
from numpy import array

def public(values):
    return array(values)
'''
    generated = '''
from numpy import array
from invented_module import public

def test_public():
    assert list(public([1])) == [1]
'''

    normalized = normalize_python_tests(generated, source)

    assert "from numpy import array" in normalized
    assert "from module_under_test import public" in normalized


def test_normalizer_converts_common_llama_unittest_patterns():
    source = 'def public(value):\n    return value / 3\n'
    generated = '''
from invented_module import public

class TestPublic:
    def test_patterns(self):
        self.assertGreater(public(6), 1)
        self.assertAlmostEqual(public(3), 1.0)
        with self.assertRaisesRegex(ZeroDivisionError, "zero"):
            public(0)
'''

    normalized = normalize_python_tests(generated, source)

    assert "assert public(6) > 1" in normalized
    assert "pytest.approx(1.0)" in normalized
    assert "with pytest.raises(ZeroDivisionError, match='zero')" in normalized


def test_normalizer_repairs_only_known_safe_missing_imports():
    source = 'def public(value):\n    return value\n'
    generated = '''
from module_under_test import public

def test_helpers():
    payload = json.dumps({"value": str(Decimal("1.5"))})
    db = MagicMock()
    fixed = datetime(2023, 1, 1)
    assert public(payload)
    assert db is not None
    assert fixed.year == 2023
'''

    normalized = normalize_python_tests(generated, source)
    ast.parse(normalized)

    assert "import json" in normalized
    assert "from decimal import Decimal" in normalized
    assert "from unittest.mock import MagicMock" in normalized
    assert "from datetime import datetime" in normalized


def test_normalizer_preserves_future_import_order_when_repairing_imports():
    source = 'def public():\n    return 1\n'
    generated = '''
"""tests"""
from __future__ import annotations
from module_under_test import public

def test_public():
    assert json.loads("1") == public()
'''

    normalized = normalize_python_tests(generated, source)

    ast.parse(normalized)
    assert normalized.index("from __future__ import annotations") < normalized.index("import json")
