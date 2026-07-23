"""Model-guided behavioral test generation for unseen Python source files.

The model proposes inputs only.  Expected values and exception types are
observed in a subprocess on the server and converted into pytest assertions by
deterministic code.  This prevents small models from repeatedly guessing the
wrong oracle while retaining their ability to choose meaningful branch inputs.
"""

from __future__ import annotations

import ast
import inspect
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from core.sandbox.resource_limits import run_limited_process
from core.source_analyzer import analyze_python_source, assess_behavioral_eligibility


_TEST_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cases": {
            "type": "array",
            "maxItems": 10,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "maxLength": 100},
                    "target": {"type": "string", "maxLength": 100},
                    "args": {"type": "array", "maxItems": 16},
                    "kwargs": {"type": "object", "maxProperties": 16},
                    "purpose": {"type": "string", "maxLength": 500},
                },
                "required": ["name", "target", "args", "kwargs", "purpose"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["cases"],
    "additionalProperties": False,
}


_PROBE_RUNNER = r'''
import ast
import asyncio
import contextlib
import copy
import importlib.util
import inspect
import io
import json
import sys


def encode(value):
    value_repr = repr(value)
    if len(value_repr) > 8000:
        value_repr = value_repr[:8000]
    literal = False
    try:
        rebuilt = ast.literal_eval(value_repr)
        literal = type(rebuilt) is type(value) and rebuilt == value
    except Exception:
        pass
    return {
        "repr": value_repr,
        "literal": literal,
        "type": type(value).__name__,
    }


source_path, case_path = sys.argv[1], sys.argv[2]
case = json.loads(open(case_path, encoding="utf-8").read())
captured_stdout = io.StringIO()
captured_stderr = io.StringIO()
phase = "import"

try:
    with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(captured_stderr):
        spec = importlib.util.spec_from_file_location("module_under_test", source_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["module_under_test"] = module
        spec.loader.exec_module(module)
        phase = "call"
        target = getattr(module, case["target"])
        args = copy.deepcopy(case.get("args", []))
        kwargs = copy.deepcopy(case.get("kwargs", {}))
        phase = "bind"
        inspect.signature(target).bind(*args, **kwargs)
        args_before = copy.deepcopy(args)
        kwargs_before = copy.deepcopy(kwargs)
        phase = "call"
        result = target(*args, **kwargs)
        if inspect.isawaitable(result):
            result = asyncio.run(result)
    payload = {
        "status": "ok",
        "result": encode(result),
        "args_before": encode(args_before),
        "args_after": encode(args),
        "kwargs_before": encode(kwargs_before),
        "kwargs_after": encode(kwargs),
    }
except BaseException as exc:
    exception = {
        "module": type(exc).__module__,
        "name": type(exc).__name__,
        "message": str(exc)[:1000],
        "phase": phase,
    }
    payload = {
        "status": "invalid_case" if phase == "bind" else "exception",
        "exception": exception,
    }

payload["stdout"] = captured_stdout.getvalue()[-2000:]
payload["stderr"] = captured_stderr.getvalue()[-2000:]
print(json.dumps(payload, ensure_ascii=False))
'''


def _response_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        return "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        )
    return str(content)


def _extract_json_object(value: Any) -> dict[str, Any]:
    """Parse a structured response strictly; never guess a JSON substring."""
    if isinstance(value, dict):
        return value
    text = _response_text(value).strip()
    fence = re.fullmatch(r"```(?:json)?\s*\n([\s\S]*?)\n```", text)
    if fence:
        text = fence.group(1).strip()
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Test plan root must be a JSON object")
    return value


def _bounded_json(value: Any, *, depth: int = 0, budget: list[int] | None = None) -> bool:
    if budget is None:
        budget = [256]
    budget[0] -= 1
    if budget[0] < 0 or depth > 6:
        return False
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, int):
        return abs(value) <= 100_000
    if isinstance(value, float):
        if not math.isfinite(value) or abs(value) > 1_000_000:
            return False
        return True
    if isinstance(value, str):
        return len(value) <= 512
    if isinstance(value, list):
        return len(value) <= 64 and all(
            _bounded_json(v, depth=depth + 1, budget=budget) for v in value
        )
    if isinstance(value, dict):
        return len(value) <= 32 and all(
            isinstance(k, str) and len(k) <= 100
            and _bounded_json(v, depth=depth + 1, budget=budget)
            for k, v in value.items()
        )
    return False


def _test_name(raw: str, target: str, index: int) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", raw or "").strip("_").lower()
    if not name:
        name = f"{target}_case_{index + 1}"
    if not name.startswith("test_"):
        name = "test_" + name
    if name[5:6].isdigit():
        name = "test_case_" + name[5:]
    return name[:100]


def _canonical_case_signature(
    target: Any,
    args: Any,
    kwargs: Any,
) -> str:
    """Return a stable input identity independent of dictionary key order."""
    return json.dumps(
        [target, args, kwargs],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _case_binds_static_contract(
    function: dict[str, Any],
    args: list[Any],
    kwargs: dict[str, Any],
) -> bool:
    """Reject obvious arity errors before probing; runtime bind remains authoritative."""
    records = function.get("parameters")
    if not isinstance(records, list):
        return True
    kind_by_name = {
        "positional_only": inspect.Parameter.POSITIONAL_ONLY,
        "positional_or_keyword": inspect.Parameter.POSITIONAL_OR_KEYWORD,
        "var_positional": inspect.Parameter.VAR_POSITIONAL,
        "keyword_only": inspect.Parameter.KEYWORD_ONLY,
        "var_keyword": inspect.Parameter.VAR_KEYWORD,
    }
    parameters: list[inspect.Parameter] = []
    try:
        for record in records:
            kind = kind_by_name[record["kind"]]
            default = inspect.Parameter.empty
            if (
                kind not in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
                and record.get("default") is not None
            ):
                default = object()
            parameters.append(
                inspect.Parameter(str(record["name"]), kind=kind, default=default)
            )
        inspect.Signature(parameters).bind(*args, **kwargs)
    except (KeyError, TypeError, ValueError):
        return False
    return True


def validate_plan(plan: dict[str, Any], analysis: dict[str, Any], max_cases: int = 10) -> list[dict[str, Any]]:
    """Keep only bounded cases targeting real top-level functions."""
    function_by_name = {item["name"]: item for item in analysis.get("functions", [])}
    allowed = set(function_by_name)
    raw_cases = plan.get("cases", [])
    if not isinstance(raw_cases, list):
        return []

    cases: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for raw in raw_cases[:max_cases]:
        if not isinstance(raw, dict):
            continue
        target = raw.get("target")
        args = raw.get("args", [])
        kwargs = raw.get("kwargs", {})
        if target not in allowed or not isinstance(args, list) or not isinstance(kwargs, dict):
            continue
        if not _bounded_json(args) or not _bounded_json(kwargs):
            continue
        if not _case_binds_static_contract(function_by_name[target], args, kwargs):
            continue
        name = _test_name(str(raw.get("name", "")), target, len(cases))
        base = name
        suffix = 2
        while name in used_names:
            name = f"{base}_{suffix}"
            suffix += 1
        used_names.add(name)
        cases.append({
            "name": name,
            "target": target,
            "args": args,
            "kwargs": kwargs,
            "purpose": str(raw.get("purpose", ""))[:500],
            "async": bool(function_by_name[target].get("async")),
        })
    return cases


def _literal_default(value: Any) -> tuple[bool, Any]:
    if not isinstance(value, str):
        return False, None
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return False, None
    return (_bounded_json(parsed), parsed)


def _shallow_annotation_values(annotation: Any, default: Any) -> list[Any]:
    """Create primitive JSON seeds only; never infer nested runtime shapes."""
    text = str(annotation or "").replace(" ", "").lower()
    permits_none = (
        "optional[" in text
        or "none" in text
        or "nonetype" in text
        or "|none" in text
        or (isinstance(default, str) and default.strip() == "None")
    )
    values: list[Any] = []
    if any(token in text for token in ("list", "sequence", "tuple", "set")):
        values.append([])
    elif any(token in text for token in ("dict", "mapping")):
        values.append({})
    elif "bool" in text:
        values.extend([False, True])
    elif "int" in text:
        values.extend([0, -1, 1])
    elif "float" in text:
        values.extend([0.0, -1.0, 1.0])
    elif "str" in text:
        values.extend(["", "a"])
    elif annotation is None:
        valid_default, literal = _literal_default(default)
        if valid_default:
            values.append(literal)
    if permits_none and None not in values:
        values.append(None)
    return values


def derive_shallow_cases(
    analysis: dict[str, Any],
    cases: list[dict[str, Any]],
    *,
    min_total_cases: int = 4,
    max_total_cases: int = 10,
) -> list[dict[str, Any]]:
    """Fill a small plan using only primitive type hints and literal defaults."""
    result = list(cases)
    signatures = {
        _canonical_case_signature(
            case.get("target"), case.get("args", []), case.get("kwargs", {})
        )
        for case in result
    }
    used_names = {str(case.get("name", "")) for case in result}
    target_count = min(min_total_cases, max_total_cases)
    if len(result) >= target_count:
        return result

    for function in analysis.get("functions", []):
        records = function.get("parameters", [])
        if not isinstance(records, list):
            continue
        parameter_values: list[tuple[dict[str, Any], list[Any]]] = []
        unsupported_required = False
        for record in records:
            kind = record.get("kind")
            if kind in {"var_positional", "var_keyword"}:
                continue
            values = _shallow_annotation_values(
                record.get("annotation"), record.get("default")
            )
            if not values:
                valid_default, literal = _literal_default(record.get("default"))
                if valid_default:
                    values = [literal]
            if not values:
                if record.get("default") is not None:
                    # Optional dynamic defaults can be safely omitted without
                    # evaluating or trying to model their runtime object.
                    continue
                unsupported_required = True
                break
            parameter_values.append((record, values))
        if unsupported_required:
            continue

        variants = max((len(values) for _, values in parameter_values), default=1)
        for variant_index in range(variants):
            args: list[Any] = []
            kwargs: dict[str, Any] = {}
            for record, values in parameter_values:
                value = values[min(variant_index, len(values) - 1)]
                if record.get("kind") == "keyword_only":
                    kwargs[str(record["name"])] = value
                else:
                    args.append(value)
            signature = _canonical_case_signature(function.get("name"), args, kwargs)
            if signature in signatures:
                continue
            base_name = _test_name(
                f"{function.get('name', 'function')}_shallow_{variant_index + 1}",
                str(function.get("name", "function")),
                len(result),
            )
            name = base_name
            suffix = 2
            while name in used_names:
                name = f"{base_name}_{suffix}"
                suffix += 1
            result.append({
                "name": name,
                "target": function.get("name"),
                "args": args,
                "kwargs": kwargs,
                "purpose": "Shallow deterministic seed from type hints",
                "async": bool(function.get("async")),
            })
            signatures.add(signature)
            used_names.add(name)
            if len(result) >= target_count or len(result) >= max_total_cases:
                return result
    return result


def request_test_plan(
    llm: Any,
    file_name: str,
    source_code: str,
    analysis: dict[str, Any],
    *,
    max_cases: int = 10,
    missing_lines: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Ask the model for JSON-serialisable inputs, never expected outputs."""
    coverage_hint = ""
    if missing_lines:
        coverage_hint = f"\nPrior tests missed source lines: {missing_lines}. Prefer inputs that reach them."

    system_prompt = (
        "You design inputs for Python characterization tests. Return JSON only. "
        "Never predict expected outputs and never write Python test code. "
        "Use only exact top-level function names from the supplied contract. "
        "All args and kwargs must be valid JSON values. Choose small deterministic inputs. "
        "Choose runtime-compatible types from the source operations: for example, a value "
        "used in arithmetic with integers must be numeric, not a numeric-looking string. "
        "Never create a case whose only behavior is an accidental builtin TypeError caused "
        "by incompatible argument types. "
        "Cover happy paths and meaningful branches, but do not add None, empty, huge, or invalid "
        "inputs unless the source contract shows that such a path exists. "
        f"Return at most {max_cases} cases using this schema: "
        '{"cases":[{"name":"descriptive name","target":"function_name",'
        '"args":[],"kwargs":{},"purpose":"branch exercised"}]}.'
    )
    user_prompt = (
        f"File: {file_name}\n\n"
        f"Static contract:\n{json.dumps(analysis, ensure_ascii=False, indent=2)}\n\n"
        f"Source:\n```python\n{source_code}\n```"
        f"{coverage_hint}"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    structured_llm = llm.bind(format=_TEST_PLAN_SCHEMA) if hasattr(llm, "bind") else llm
    response = structured_llm.invoke(messages)
    return validate_plan(_extract_json_object(response), analysis, max_cases=max_cases)


def _simple_values(test: ast.AST, parameter_names: set[str]) -> list[tuple[str, Any, str]]:
    """Solve only transparent predicates; opaque calls such as hash(x) are skipped."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) and isinstance(test.operand, ast.Name):
        if test.operand.id in parameter_names:
            return [(test.operand.id, False, "false branch"), (test.operand.id, True, "true branch")]
    if isinstance(test, ast.Name) and test.id in parameter_names:
        return [(test.id, False, "false branch"), (test.id, True, "true branch")]
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 or len(test.comparators) != 1:
        return []

    left, right = test.left, test.comparators[0]
    if isinstance(left, ast.Name) and left.id in parameter_names and isinstance(right, ast.Constant):
        parameter, constant = left.id, right.value
    elif isinstance(right, ast.Name) and right.id in parameter_names and isinstance(left, ast.Constant):
        parameter, constant = right.id, left.value
    else:
        # Handle x % modulus == residue without pretending to solve arbitrary calls.
        modulo = left if isinstance(left, ast.BinOp) and isinstance(left.op, ast.Mod) else None
        if (
            modulo and isinstance(modulo.left, ast.Name) and modulo.left.id in parameter_names
            and isinstance(modulo.right, ast.Constant) and isinstance(modulo.right.value, int)
            and isinstance(right, ast.Constant) and isinstance(right.value, int)
            and isinstance(test.ops[0], (ast.Eq, ast.NotEq)) and modulo.right.value != 0
        ):
            residue = right.value % abs(modulo.right.value)
            other = (residue + 1) % abs(modulo.right.value)
            return [
                (modulo.left.id, residue, "modulo predicate matches"),
                (modulo.left.id, other, "modulo predicate does not match"),
            ]
        return []

    if isinstance(constant, bool):
        return [(parameter, False, "boolean boundary"), (parameter, True, "boolean boundary")]
    if isinstance(constant, int) and abs(constant) <= 99_999:
        return [
            (parameter, constant - 1, "numeric boundary below"),
            (parameter, constant, "numeric boundary equal"),
            (parameter, constant + 1, "numeric boundary above"),
        ]
    if isinstance(constant, float) and math.isfinite(constant) and abs(constant) <= 999_999:
        delta = max(1e-6, abs(constant) * 1e-6)
        return [
            (parameter, constant - delta, "numeric boundary below"),
            (parameter, constant, "numeric boundary equal"),
            (parameter, constant + delta, "numeric boundary above"),
        ]
    if isinstance(constant, str) and len(constant) <= 500:
        return [
            (parameter, constant, "string predicate matches"),
            (parameter, constant + "__other", "string predicate does not match"),
        ]
    return []


def _replace_case_parameter(
    case: dict[str, Any],
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    parameter: str,
    value: Any,
) -> dict[str, Any] | None:
    args = list(case.get("args", []))
    kwargs = dict(case.get("kwargs", {}))
    positional = [*function.args.posonlyargs, *function.args.args]
    positions = {argument.arg: index for index, argument in enumerate(positional)}
    position = positions.get(parameter)
    if position is not None and position < len(args):
        args[position] = value
    elif parameter in kwargs or parameter not in {arg.arg for arg in function.args.posonlyargs}:
        kwargs[parameter] = value
    else:
        return None
    if not _bounded_json(args) or not _bounded_json(kwargs):
        return None
    return {**case, "args": args, "kwargs": kwargs}


class _BranchCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.nodes: list[ast.If | ast.While] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_If(self, node: ast.If) -> None:
        self.nodes.append(node)
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.nodes.append(node)
        self.generic_visit(node)


def derive_boundary_cases(
    source_code: str,
    cases: list[dict[str, Any]],
    *,
    max_total_cases: int = 10,
) -> list[dict[str, Any]]:
    """Add bounded cases for simple predicates without another model call."""
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return cases
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    result = list(cases)
    signatures = {
        _canonical_case_signature(
            case.get("target"), case.get("args", []), case.get("kwargs", {})
        )
        for case in result
    }
    name_counter = 1
    for target, function in functions.items():
        base = next((case for case in cases if case.get("target") == target), None)
        if base is None:
            continue
        parameter_names = {
            arg.arg
            for arg in [
                *function.args.posonlyargs,
                *function.args.args,
                *function.args.kwonlyargs,
            ]
        }
        collector = _BranchCollector()
        for statement in function.body:
            collector.visit(statement)
        for node in collector.nodes:
            for parameter, value, purpose in _simple_values(node.test, parameter_names):
                candidate = _replace_case_parameter(base, function, parameter, value)
                if candidate is None:
                    continue
                signature = _canonical_case_signature(
                    target, candidate.get("args", []), candidate.get("kwargs", {})
                )
                if signature in signatures:
                    continue
                candidate["name"] = _test_name(
                    f"{target}_{parameter}_boundary_{name_counter}", target, len(result)
                )
                candidate["purpose"] = f"Static solver: line {node.lineno}, {purpose}"
                candidate["async"] = isinstance(function, ast.AsyncFunctionDef)
                result.append(candidate)
                signatures.add(signature)
                name_counter += 1
                if len(result) >= max_total_cases:
                    return result
    return result


def probe_cases(
    source_code: str,
    cases: list[dict[str, Any]],
    *,
    timeout_per_case: float = 5.0,
) -> list[dict[str, Any]]:
    """Observe each planned call in a fresh subprocess with a hard timeout."""
    observations: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        source_path = temp_path / "module_under_test.py"
        runner_path = temp_path / "probe_runner.py"
        source_path.write_text(source_code, encoding="utf-8")
        runner_path.write_text(_PROBE_RUNNER, encoding="utf-8")
        if os.name == "posix":
            temp_path.chmod(0o777)

        for index, case in enumerate(cases):
            case_path = temp_path / f"case_{index}.json"
            case_path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
            try:
                completed = run_limited_process(
                    [sys.executable, str(runner_path), str(source_path), str(case_path)],
                    cwd=temp_dir,
                    env={**os.environ, "HOME": temp_dir, "PYTHONPATH": temp_dir},
                    timeout=timeout_per_case,
                    memory_mb=384,
                    cpu_seconds=max(1, int(timeout_per_case)),
                    file_size_mb=2,
                    max_files=32,
                    max_processes=8,
                )
                lines = [line for line in completed.stdout.splitlines() if line.strip()]
                payload = json.loads(lines[-1]) if lines else {
                    "status": "probe_error",
                    "error": completed.stderr[-2000:] or "Probe returned no JSON",
                }
            except subprocess.TimeoutExpired:
                payload = {"status": "timeout", "error": f"Exceeded {timeout_per_case:.1f}s"}
            except Exception as exc:
                payload = {"status": "probe_error", "error": str(exc)}
            observations.append({"case": case, "observation": payload})
    return observations


def _declared_exception_names(
    analysis: dict[str, Any], target: str
) -> set[str]:
    """Return exception names explicitly raised by one top-level function."""
    function = next(
        (
            item
            for item in analysis.get("functions", [])
            if item.get("name") == target
        ),
        {},
    )
    names: set[str] = set()
    for record in function.get("raises", []):
        if not isinstance(record, dict):
            continue
        raw = record.get("exception")
        if not isinstance(raw, str):
            continue
        name = raw.rsplit(".", 1)[-1]
        if name.isidentifier():
            names.add(name)
    return names


def reject_accidental_type_errors(
    observations: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> list[dict[str, Any]]:
    """Reject model inputs that only characterize an accidental type mismatch.

    Runtime signature binding proves arity, but Python cannot use it to reject
    ``target='4'`` for an unannotated numeric parameter.  A builtin TypeError
    produced by such a call is therefore treated as an invalid probe unless the
    target function explicitly contains ``raise TypeError``.  Explicit error
    contracts remain characterizable while garbage type combinations cannot
    become passing coverage tests.
    """
    filtered: list[dict[str, Any]] = []
    for item in observations:
        observation = item.get("observation", {})
        exception = observation.get("exception", {})
        target = str(item.get("case", {}).get("target", ""))
        is_accidental_type_error = (
            observation.get("status") == "exception"
            and exception.get("phase") == "call"
            and exception.get("module") == "builtins"
            and exception.get("name") == "TypeError"
            and "TypeError" not in _declared_exception_names(analysis, target)
        )
        if is_accidental_type_error:
            observation = {
                **observation,
                "status": "invalid_case",
                "invalid_reason": "accidental_builtin_type_error",
            }
            item = {**item, "observation": observation}
        filtered.append(item)
    return filtered


def _call_expression(case: dict[str, Any], args_expression: str | None = None, kwargs_expression: str | None = None) -> str:
    if args_expression is not None:
        args = f"*{args_expression}"
    else:
        args = f"*{case.get('args', [])!r}"
    if kwargs_expression is not None:
        kwargs = f"**{kwargs_expression}"
    else:
        kwargs = f"**{case.get('kwargs', {})!r}"
    separator = ", " if args and kwargs else ""
    call = f"mut.{case['target']}({args}{separator}{kwargs})"
    return f"asyncio.run({call})" if case.get("async") else call


def _exception_expression(info: dict[str, Any]) -> str:
    name = str(info.get("name", "Exception"))
    if not name.isidentifier():
        return "Exception"
    return name if info.get("module") == "builtins" else f"mut.{name}"


def emit_pytest(observations: list[dict[str, Any]]) -> str:
    """Turn successful observations into a complete deterministic pytest file."""
    blocks = ["import pytest", "import module_under_test as mut"]
    if any(item.get("case", {}).get("async") for item in observations):
        blocks.append("import asyncio")
    emitted = 0
    for item in observations:
        case = item["case"]
        observation = item["observation"]
        status = observation.get("status")
        if status not in {"ok", "exception"}:
            continue
        if status == "exception" and observation.get("exception", {}).get("phase") != "call":
            continue

        lines = [f"def {case['name']}():"]
        purpose = case.get("purpose", "").replace("\n", " ").strip()
        if purpose:
            lines.append(f"    # {purpose}")

        if status == "exception":
            exception = _exception_expression(observation.get("exception", {}))
            lines.append(f"    with pytest.raises({exception}):")
            lines.append(f"        {_call_expression(case)}")
        else:
            args_before = observation.get("args_before", {})
            args_after = observation.get("args_after", {})
            kwargs_before = observation.get("kwargs_before", {})
            kwargs_after = observation.get("kwargs_after", {})
            mutated = (
                args_before.get("repr") != args_after.get("repr")
                or kwargs_before.get("repr") != kwargs_after.get("repr")
            )
            if mutated and all(
                value.get("literal")
                for value in (args_before, args_after, kwargs_before, kwargs_after)
            ):
                lines.append(f"    args = {args_before['repr']}")
                lines.append(f"    kwargs = {kwargs_before['repr']}")
                lines.append(f"    actual = {_call_expression(case, 'args', 'kwargs')}")
                lines.append(f"    assert args == {args_after['repr']}")
                lines.append(f"    assert kwargs == {kwargs_after['repr']}")
            else:
                lines.append(f"    actual = {_call_expression(case)}")

            result = observation.get("result", {})
            if result.get("literal"):
                lines.append(f"    assert actual == {result['repr']}")
            else:
                type_name = str(result.get("type", "object"))
                lines.append(f"    assert type(actual).__name__ == {type_name!r}")

        blocks.append("\n".join(lines))
        emitted += 1

    return "\n\n".join(blocks) + "\n" if emitted else ""


def _emitted_test_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    literals: dict[str, Any] = {}
    for child in node.body:
        if (
            isinstance(child, ast.Assign)
            and len(child.targets) == 1
            and isinstance(child.targets[0], ast.Name)
        ):
            try:
                literals[child.targets[0].id] = ast.literal_eval(child.value)
            except (ValueError, TypeError):
                pass
    for call in (child for child in ast.walk(node) if isinstance(child, ast.Call)):
        if not (
            isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id in {"mut", "module_under_test"}
        ):
            continue
        try:
            args: list[Any] = []
            for value in call.args:
                if isinstance(value, ast.Starred):
                    expanded = (
                        literals[value.value.id]
                        if isinstance(value.value, ast.Name) and value.value.id in literals
                        else ast.literal_eval(value.value)
                    )
                    args.extend(expanded)
                else:
                    args.append(ast.literal_eval(value))
            kwargs: dict[str, Any] = {}
            for keyword in call.keywords:
                if keyword.arg is None:
                    expanded = (
                        literals[keyword.value.id]
                        if isinstance(keyword.value, ast.Name) and keyword.value.id in literals
                        else ast.literal_eval(keyword.value)
                    )
                    kwargs.update(expanded)
                else:
                    kwargs[keyword.arg] = ast.literal_eval(keyword.value)
            return _canonical_case_signature(call.func.attr, args, kwargs)
        except (KeyError, TypeError, ValueError):
            return None
    return None


def _test_body_fingerprint(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    return ast.dump(
        ast.Module(body=node.body, type_ignores=[]),
        annotate_fields=True,
        include_attributes=False,
    )


def merge_pytest_files(existing_code: str, additional_code: str) -> str:
    """Merge novel expansion inputs and deterministically rename collisions."""
    try:
        existing_tree = ast.parse(existing_code)
        additional_tree = ast.parse(additional_code)
    except SyntaxError:
        return existing_code

    existing_names = {
        node.name
        for node in existing_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    existing_functions = [
        node for node in existing_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]
    existing_signatures = {
        signature for node in existing_functions
        if (signature := _emitted_test_signature(node)) is not None
    }
    existing_fingerprints = {_test_body_fingerprint(node) for node in existing_functions}
    additions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in additional_tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test_"):
            continue
        signature = _emitted_test_signature(node)
        fingerprint = _test_body_fingerprint(node)
        if (
            signature is not None and signature in existing_signatures
        ) or (
            signature is None and fingerprint in existing_fingerprints
        ):
            continue
        if node.name in existing_names:
            base_name = f"{node.name}_expansion"
            candidate = f"{base_name}_2"
            suffix = 3
            while candidate in existing_names:
                candidate = f"{base_name}_{suffix}"
                suffix += 1
            node.name = candidate
        additions.append(node)
        existing_names.add(node.name)
        if signature is not None:
            existing_signatures.add(signature)
        existing_fingerprints.add(fingerprint)
    if not additions:
        return existing_code
    existing_imports = {
        ast.dump(node, include_attributes=False)
        for node in existing_tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    }
    new_imports = [
        node for node in additional_tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and ast.dump(node, include_attributes=False) not in existing_imports
    ]
    insert_at = 0
    while insert_at < len(existing_tree.body) and isinstance(
        existing_tree.body[insert_at], (ast.Import, ast.ImportFrom)
    ):
        insert_at += 1
    existing_tree.body[insert_at:insert_at] = new_imports
    existing_tree.body.extend(additions)
    ast.fix_missing_locations(existing_tree)
    return ast.unparse(existing_tree) + "\n"


def build_behavioral_candidate(
    llm: Any,
    file_name: str,
    source_code: str,
    *,
    max_cases: int = 10,
    missing_lines: list[int] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build a pytest candidate and return diagnostics for tracing/fallback."""
    analysis = analyze_python_source(source_code)
    eligibility = analysis.get("behavioral_eligibility") or assess_behavioral_eligibility(analysis)
    diagnostics: dict[str, Any] = {
        "analysis": analysis,
        "eligibility": eligibility,
        "cases": [],
        "observations": [],
    }
    if not analysis.get("valid") or not analysis.get("functions"):
        diagnostics["reason"] = "No valid top-level Python functions"
        return "", diagnostics
    if not eligibility.get("eligible"):
        diagnostics["reason"] = "Behavioral probing rejected by safety gate: " + ", ".join(
            eligibility.get("reasons", [])
        )
        return "", diagnostics

    try:
        model_case_budget = min(max_cases, 6)
        cases = request_test_plan(
            llm,
            file_name,
            source_code,
            analysis,
            max_cases=model_case_budget,
            missing_lines=missing_lines,
        )
        cases = derive_shallow_cases(
            analysis,
            cases,
            min_total_cases=min(4, max_cases),
            max_total_cases=max_cases,
        )
        cases = derive_boundary_cases(source_code, cases, max_total_cases=max_cases)
    except Exception as exc:
        diagnostics["reason"] = f"Invalid behavioral plan: {exc}"
        return "", diagnostics

    diagnostics["cases"] = cases
    if not cases:
        diagnostics["reason"] = "Behavioral plan contained no valid cases"
        return "", diagnostics

    observations = reject_accidental_type_errors(
        probe_cases(source_code, cases),
        analysis,
    )
    diagnostics["observations"] = observations
    code = emit_pytest(observations)
    if not code:
        diagnostics["reason"] = "No probe produced an assertable observation"
    return code, diagnostics
