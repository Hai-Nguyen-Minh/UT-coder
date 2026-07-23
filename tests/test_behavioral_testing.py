import ast
import json

from core.behavioral_testing import (
    build_behavioral_candidate,
    derive_boundary_cases,
    derive_shallow_cases,
    emit_pytest,
    merge_pytest_files,
    probe_cases,
    reject_accidental_type_errors,
    request_test_plan,
    validate_plan,
)
from core.sandbox.python_sandbox import PythonSandbox


SOURCE = '''
def classify(number):
    if number < 0:
        raise ValueError("negative")
    if number == 0:
        return "zero"
    return number * 2

def append_marker(values):
    values.append("done")
    return len(values)
'''


class _Response:
    def __init__(self, content):
        self.content = content


class _FakeLlm:
    def invoke(self, messages):
        plan = {
            "cases": [
                {"name": "negative is observed", "target": "classify", "args": [-1], "kwargs": {}, "purpose": "negative branch"},
                {"name": "zero", "target": "classify", "args": [0], "kwargs": {}, "purpose": "zero branch"},
                {"name": "positive", "target": "classify", "args": [4], "kwargs": {}, "purpose": "positive branch"},
                {"name": "mutation", "target": "append_marker", "args": [["start"]], "kwargs": {}, "purpose": "argument mutation"},
                {"name": "hallucinated", "target": "missing_function", "args": [], "kwargs": {}, "purpose": "must be rejected"},
            ]
        }
        return _Response("```json\n" + json.dumps(plan) + "\n```")


class _StructuredFakeLlm:
    def __init__(self):
        self.bound_format = None

    def bind(self, **kwargs):
        self.bound_format = kwargs.get("format")
        return self

    def invoke(self, messages):
        return {
            "cases": [{
                "name": "small",
                "target": "classify",
                "args": [1],
                "kwargs": {},
                "purpose": "positive branch",
            }]
        }


def test_behavioral_candidate_observes_oracles_and_passes_in_sandbox():
    code, diagnostics = build_behavioral_candidate(_FakeLlm(), "unseen.py", SOURCE)

    ast.parse(code)
    assert len(diagnostics["cases"]) >= 4
    assert "missing_function" not in code
    assert "pytest.raises(ValueError)" in code
    assert "assert actual == 'zero'" in code
    assert "assert args == [['start', 'done']]" in code

    result = PythonSandbox().run_test("unseen.py", SOURCE, code)
    assert result.success is True, result.error_log
    assert result.coverage == 100.0


def test_plan_uses_ollama_json_schema_when_bind_is_available():
    llm = _StructuredFakeLlm()
    analysis = {
        "functions": [{"name": "classify", "async": False}],
    }

    cases = request_test_plan(llm, "unseen.py", SOURCE, analysis)

    assert llm.bound_format["type"] == "object"
    assert llm.bound_format["additionalProperties"] is False
    assert cases[0]["target"] == "classify"


def test_plan_rejects_resource_exhaustion_input():
    analysis = {
        "functions": [{"name": "allocate", "async": False}],
    }
    plan = {
        "cases": [
            {"name": "oom", "target": "allocate", "args": [10**9], "kwargs": {}},
            {"name": "safe", "target": "allocate", "args": [10], "kwargs": {}},
        ]
    }

    cases = validate_plan(plan, analysis)

    assert [case["name"] for case in cases] == ["test_safe"]


def test_static_solver_skips_opaque_hash_constraint():
    source = '''
def opaque(name):
    if hash(name) % 1007 == 42:
        return "rare"
    return "common"
'''
    base = [{
        "name": "test_opaque",
        "target": "opaque",
        "args": ["alice"],
        "kwargs": {},
        "purpose": "base",
        "async": False,
    }]

    assert derive_boundary_cases(source, base) == base


def test_import_failure_is_not_emitted_as_expected_call_exception():
    cases = [{
        "name": "test_call",
        "target": "call",
        "args": [],
        "kwargs": {},
        "purpose": "must not characterize import failure",
        "async": False,
    }]
    observations = probe_cases('raise RuntimeError("during import")\ndef call():\n    return 1\n', cases)

    assert observations[0]["observation"]["exception"]["phase"] == "import"
    assert emit_pytest(observations) == ""


def test_async_function_is_emitted_with_asyncio_run():
    source = 'async def double(value):\n    return value * 2\n'
    cases = [{
        "name": "test_double",
        "target": "double",
        "args": [4],
        "kwargs": {},
        "purpose": "async path",
        "async": True,
    }]

    code = emit_pytest(probe_cases(source, cases))

    assert "import asyncio" in code
    assert "asyncio.run(mut.double" in code


def test_wrong_arity_is_rejected_instead_of_characterized_as_type_error():
    source = "def single(value):\n    return value\n"
    cases = [{
        "name": "test_wrong_arity",
        "target": "single",
        "args": [1, 2],
        "kwargs": {},
        "purpose": "invalid model proposal",
        "async": False,
    }]

    observations = probe_cases(source, cases)

    assert observations[0]["observation"]["status"] == "invalid_case"
    assert observations[0]["observation"]["exception"]["phase"] == "bind"
    assert emit_pytest(observations) == ""


def test_accidental_builtin_type_error_is_rejected_for_unannotated_input():
    source = '''
def two_sum_indices(nums, target):
    seen = {}
    for index, value in enumerate(nums):
        need = target - value
        if need in seen:
            return (seen[need], index)
        seen[value] = index
    return None
'''
    analysis = {
        "functions": [{
            "name": "two_sum_indices",
            "raises": [],
        }],
    }
    cases = [{
        "name": "test_numeric_looking_string",
        "target": "two_sum_indices",
        "args": [[1, 2, 3], "4"],
        "kwargs": {},
        "purpose": "invalid model proposal",
        "async": False,
    }]

    observations = reject_accidental_type_errors(
        probe_cases(source, cases), analysis
    )

    assert observations[0]["observation"]["status"] == "invalid_case"
    assert (
        observations[0]["observation"]["invalid_reason"]
        == "accidental_builtin_type_error"
    )
    assert emit_pytest(observations) == ""


def test_explicit_type_error_contract_is_still_characterized():
    source = '''
def require_text(value):
    if not isinstance(value, str):
        raise TypeError("value must be text")
    return value.upper()
'''
    analysis = {
        "functions": [{
            "name": "require_text",
            "raises": [{"line": 4, "exception": "TypeError"}],
        }],
    }
    cases = [{
        "name": "test_rejects_non_text",
        "target": "require_text",
        "args": [7],
        "kwargs": {},
        "purpose": "explicit error contract",
        "async": False,
    }]

    observations = reject_accidental_type_errors(
        probe_cases(source, cases), analysis
    )
    code = emit_pytest(observations)

    assert observations[0]["observation"]["status"] == "exception"
    assert "pytest.raises(TypeError)" in code


def test_behavioral_candidate_falls_back_instead_of_emitting_type_error_garbage():
    source = '''
def two_sum_indices(nums, target):
    seen = {}
    for index, value in enumerate(nums):
        need = target - value
        if need in seen:
            return (seen[need], index)
        seen[value] = index
    return None
'''

    class WrongTypeLlm:
        def bind(self, **_kwargs):
            return self

        def invoke(self, _messages):
            return {
                "cases": [{
                    "name": "happy path",
                    "target": "two_sum_indices",
                    "args": [[1, 2, 3], "4"],
                    "kwargs": {},
                    "purpose": "both numbers found",
                }]
            }

    code, diagnostics = build_behavioral_candidate(
        WrongTypeLlm(), "task_unseen_31.py", source
    )

    assert code == ""
    assert diagnostics["observations"][0]["observation"]["status"] == "invalid_case"
    assert diagnostics["reason"] == "No probe produced an assertable observation"


def test_plan_statically_rejects_clear_arity_mismatch():
    analysis = {
        "functions": [{
            "name": "single",
            "async": False,
            "parameters": [{
                "name": "value",
                "kind": "positional_or_keyword",
                "annotation": "int",
                "default": None,
            }],
        }],
    }
    plan = {"cases": [{
        "name": "wrong",
        "target": "single",
        "args": [1, 2],
        "kwargs": {},
        "purpose": "wrong arity",
    }]}

    assert validate_plan(plan, analysis) == []


def test_shallow_seed_generation_uses_only_primitive_type_hints():
    analysis = {
        "functions": [{
            "name": "combine",
            "async": False,
            "parameters": [
                {"name": "count", "kind": "positional_or_keyword", "annotation": "int", "default": None},
                {"name": "label", "kind": "positional_or_keyword", "annotation": "str", "default": None},
            ],
        }],
    }

    cases = derive_shallow_cases(analysis, [], min_total_cases=3)

    assert [case["args"] for case in cases] == [[0, ""], [-1, "a"], [1, "a"]]
    assert all(case["kwargs"] == {} for case in cases)


def test_shallow_seed_generation_skips_unknown_required_objects():
    analysis = {
        "functions": [{
            "name": "visit",
            "async": False,
            "parameters": [{
                "name": "node",
                "kind": "positional_or_keyword",
                "annotation": None,
                "default": None,
            }],
        }],
    }

    assert derive_shallow_cases(analysis, []) == []


def test_shallow_seed_generation_does_not_infer_nested_container_shape():
    analysis = {
        "functions": [{
            "name": "flatten",
            "async": False,
            "parameters": [{
                "name": "values",
                "kind": "positional_or_keyword",
                "annotation": "list[list[int]]",
                "default": None,
            }],
        }],
    }

    cases = derive_shallow_cases(analysis, [])

    assert [case["args"] for case in cases] == [[[]]]


def test_coverage_merge_deduplicates_inputs_and_renames_novel_name_collision():
    source = "def lookup(data):\n    return sorted(data.items())\n"
    base_case = [{
        "name": "test_lookup",
        "target": "lookup",
        "args": [{"a": 1, "b": 2}],
        "kwargs": {},
        "purpose": "base",
        "async": False,
    }]
    duplicate_case = [{**base_case[0], "args": [{"b": 2, "a": 1}]}]
    novel_case = [{**base_case[0], "args": [{"c": 3}]}]
    base_code = emit_pytest(probe_cases(source, base_case))

    duplicate_merge = merge_pytest_files(
        base_code, emit_pytest(probe_cases(source, duplicate_case))
    )
    novel_merge = merge_pytest_files(
        base_code, emit_pytest(probe_cases(source, novel_case))
    )

    assert duplicate_merge == base_code
    assert "def test_lookup_expansion_2" in novel_merge
