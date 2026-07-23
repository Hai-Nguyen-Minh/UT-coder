import importlib
import sys
import types

from core.sandbox.base import SandboxResult


def test_passing_low_coverage_continues_into_self_reflection(monkeypatch):
    code_parser = types.ModuleType("core.code_parser")
    code_parser.detect_language = lambda _name: "python"
    code_parser.parse_code = lambda _name, _source: []
    config = types.ModuleType("core.config")
    config.get_config = lambda: {"languages": {"python": {"test_framework": "pytest"}}}

    class Chunk:
        content = '''```python
import pytest
from module_under_test import classify

def test_zero():
    assert classify(0) == "zero"

def test_positive():
    assert classify(2) == "positive"
```'''

    class FakeLlm:
        def __init__(self):
            self.stream_calls = 0

        def stream(self, _messages):
            self.stream_calls += 1
            return iter([Chunk()])

    fake_llm = FakeLlm()
    llm_module = types.ModuleType("core.llm")
    llm_module.get_llm = lambda: fake_llm
    vectorstore = types.ModuleType("core.vectorstore")
    vectorstore.index_documents = lambda _docs, _collection: None
    vectorstore.similarity_search = lambda **_kwargs: []

    monkeypatch.setitem(sys.modules, "core.code_parser", code_parser)
    monkeypatch.setitem(sys.modules, "core.config", config)
    monkeypatch.setitem(sys.modules, "core.llm", llm_module)
    monkeypatch.setitem(sys.modules, "core.vectorstore", vectorstore)
    sys.modules.pop("core.generator", None)
    generator = importlib.import_module("core.generator")

    class FakeSandbox:
        def __init__(self):
            self.results = [
                SandboxResult(
                    success=True,
                    stdout="1 passed",
                    stderr="",
                    coverage=40.0,
                    missing_lines=[4],
                    execution_status="tests_passed",
                    coverage_valid=True,
                    tests_collected=1,
                    tests_passed=1,
                    tests_failed=0,
                ),
                SandboxResult(
                    success=True,
                    stdout="2 passed",
                    stderr="",
                    coverage=100.0,
                    missing_lines=[],
                    execution_status="tests_passed",
                    coverage_valid=True,
                    tests_collected=2,
                    tests_passed=2,
                    tests_failed=0,
                ),
            ]

        def run_test(
            self,
            _file_name,
            _source_code,
            _test_code,
            *,
            project_files=None,
        ):
            assert project_files is None
            return self.results.pop(0)

    sandbox = FakeSandbox()
    import core.sandbox
    import core.behavioral_testing

    monkeypatch.setattr(core.sandbox, "get_sandbox", lambda _language: sandbox)

    initial_code = '''
import pytest
from module_under_test import classify

def test_zero():
    assert classify(0) == "zero"
'''

    def fake_behavioral(_llm, _file, _source, *, missing_lines=None, **_kwargs):
        if missing_lines:
            return "", {"reason": "no novel deterministic case"}
        return initial_code, {"observations": [{}]}

    monkeypatch.setattr(
        core.behavioral_testing,
        "build_behavioral_candidate",
        fake_behavioral,
    )

    events = list(generator.generate_with_reflection(
        "sample.py",
        '''
def classify(value):
    if value == 0:
        return "zero"
    return "positive"
''',
        max_retries=3,
        target_coverage=80.0,
    ))

    assert fake_llm.stream_calls == 1
    assert sandbox.results == []
    assert any("coverage self-reflection" in status for status, _, _ in events)
    assert events[-1][2]["success"] is True
    assert events[-1][2]["coverage"] == 100.0
