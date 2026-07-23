import json
import tempfile
from pathlib import Path

from core.sandbox.python_sandbox import (
    PythonSandbox,
    _pytest_execution_status,
    _read_current_coverage,
    _safe_missing_parent,
)


def test_pytest_return_codes_have_explicit_states():
    assert _pytest_execution_status(0, "") == "tests_passed"
    assert _pytest_execution_status(1, "") == "tests_failed"
    assert _pytest_execution_status(2, "ERROR collecting test_x.py") == "collection_error"
    assert _pytest_execution_status(5, "") == "no_tests_collected"
    assert _pytest_execution_status(-9, "") == "process_crash"


def test_collection_error_never_accepts_a_coverage_artifact():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "coverage.json"
        path.write_text(json.dumps({
            "totals": {"percent_covered": 100},
            "files": {"module_under_test.py": {"missing_lines": []}},
        }), encoding="utf-8")

        coverage, missing, valid = _read_current_coverage(
            path,
            module_name="module_under_test",
            started_ns=0,
            execution_status="collection_error",
        )

    assert coverage is None
    assert missing == []
    assert valid is False


def test_failed_tests_can_expose_current_coverage_for_diagnostics():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "coverage.json"
        path.write_text(json.dumps({
            "totals": {"percent_covered": 78.5},
            "files": {"module_under_test.py": {"missing_lines": [4, 8]}},
        }), encoding="utf-8")

        coverage, missing, valid = _read_current_coverage(
            path,
            module_name="module_under_test",
            started_ns=0,
            execution_status="tests_failed",
        )

    assert coverage == 78.5
    assert missing == [4, 8]
    assert valid is True


def test_directory_retry_requires_relative_write_open_in_generated_test():
    test_code = '''
def test_write():
    with open("path/to/data.json", "w") as handle:
        handle.write("{}")
'''
    output = "FileNotFoundError: [Errno 2] No such file or directory: 'path/to/data.json'\ntest_module_under_test.py:3: FileNotFoundError"
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        parent = _safe_missing_parent(
            root,
            test_file_name="test_module_under_test.py",
            test_code=test_code,
            output=output,
        )

        assert parent == (root / "path" / "to").resolve()


def test_directory_retry_rejects_source_origin_and_parent_traversal():
    test_code = 'def test_write():\n    open("../escape/data.json", "w")\n'
    source_output = "FileNotFoundError: [Errno 2] No such file or directory: '../escape/data.json'\nmodule_under_test.py:2: FileNotFoundError"
    test_output = "FileNotFoundError: [Errno 2] No such file or directory: '../escape/data.json'\ntest_module_under_test.py:2: FileNotFoundError"
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        assert _safe_missing_parent(
            root,
            test_file_name="test_module_under_test.py",
            test_code=test_code,
            output=source_output,
        ) is None
        assert _safe_missing_parent(
            root,
            test_file_name="test_module_under_test.py",
            test_code=test_code,
            output=test_output,
        ) is None


def test_compile_error_has_no_coverage():
    result = PythonSandbox().run_test(
        "broken.py",
        "def broken(:\n    pass\n",
        "def test_broken():\n    assert True\n",
    )

    assert result.success is False
    assert result.execution_status == "source_compile_error"
    assert result.coverage is None
    assert result.coverage_valid is False


def test_failed_assertion_keeps_diagnostic_coverage_but_is_not_success():
    result = PythonSandbox().run_test(
        "value.py",
        "def value():\n    return 1\n",
        "from module_under_test import value\n\ndef test_value():\n    assert value() == 2\n",
    )

    assert result.success is False
    assert result.execution_status == "tests_failed"
    assert result.coverage == 100.0
    assert result.coverage_valid is True
    assert result.tests_failed == 1


def test_collection_error_has_no_valid_coverage():
    result = PythonSandbox().run_test(
        "value.py",
        "def value():\n    return 1\n",
        "import definitely_missing_dependency\n\ndef test_value():\n    assert True\n",
    )

    assert result.success is False
    assert result.execution_status == "collection_error"
    assert result.coverage is None
    assert result.coverage_valid is False


def test_safe_missing_write_directory_gets_one_fast_retry():
    source = 'def load(path):\n    with open(path, encoding="utf-8") as handle:\n        return handle.read()\n'
    test = '''
from module_under_test import load

def test_load():
    with open("path/to/data.txt", "w", encoding="utf-8") as handle:
        handle.write("ready")
    assert load("path/to/data.txt") == "ready"
'''

    result = PythonSandbox().run_test("loader.py", source, test)

    assert result.success is True, result.error_log
    assert result.execution_status == "tests_passed"
    assert result.coverage_valid is True
    assert result.coverage == 100.0


def test_python_sandbox_materializes_nested_project_support_files():
    source = """from domain.models import Value

def unwrap(value: Value) -> int:
    return value.raw
"""
    test = """from domain.models import Value
from module_under_test import unwrap

def test_unwrap():
    assert unwrap(Value(7)) == 7
"""
    result = PythonSandbox().run_test(
        "service.py",
        source,
        test,
        project_files={
            "domain/__init__.py": "",
            "domain/models.py": (
                "class Value:\n"
                "    def __init__(self, raw):\n"
                "        self.raw = raw\n"
            ),
        },
    )

    assert result.success is True, result.error_log
    assert result.execution_status == "tests_passed"
    assert result.coverage == 100.0
