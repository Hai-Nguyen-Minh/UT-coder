"""Static source-contract extraction for model-guided test generation.

The analyser deliberately reports facts that can be obtained from Python's AST
without asking the model to infer them.  It is used for unseen source files, so
it never relies on task ids, dataset answers, or source hashes.
"""

from __future__ import annotations

import ast
import re
from typing import Any


_EXTERNAL_CALL_ROOTS = {
    "__import__": "dynamic_execution",
    "compile": "dynamic_execution",
    "eval": "dynamic_execution",
    "exec": "dynamic_execution",
    "input": "environment",
    "open": "file_io",
    "requests": "network",
    "urllib": "network",
    "httpx": "network",
    "socket": "network",
    "random": "randomness",
    "secrets": "randomness",
    "time": "time",
    "os": "environment",
    "subprocess": "process",
}

_NONDETERMINISTIC_CALL_SUFFIXES = {"now", "utcnow", "today"}

_SAFE_IMPORT_ROOTS = {
    "__future__", "abc", "bisect", "collections", "csv", "dataclasses",
    "datetime", "decimal", "enum", "fractions", "functools", "heapq", "io",
    "itertools", "json", "math", "operator", "re", "statistics", "string",
    "typing", "unicodedata",
}

_JSON_SAFE_ANNOTATIONS = {
    "any", "bool", "dict", "float", "int", "list", "mapping", "none",
    "nonetype", "object", "optional", "sequence", "str", "union",
}

_JSON_VALUE_ATTRIBUTES = {
    "add", "append", "capitalize", "casefold", "center", "clear", "copy",
    "count", "discard", "endswith", "extend", "find", "format", "get",
    "index", "insert", "isalnum", "isalpha", "isdigit", "islower",
    "isspace", "istitle", "isupper", "items", "join", "keys", "lower",
    "lstrip", "partition", "pop", "remove", "replace", "reverse", "rfind",
    "rindex", "rpartition", "rsplit", "rstrip", "setdefault", "sort",
    "split", "splitlines", "startswith", "strip", "swapcase", "title",
    "translate", "update", "upper", "values", "zfill",
}


def _unparse(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return None


def _call_name(node: ast.Call) -> str:
    return _unparse(node.func) or ""


def _external_call_category(name: str) -> str | None:
    """Classify effects at call granularity so deterministic stdlib stays probeable."""
    suffix = name.rsplit(".", 1)[-1].lower()
    if suffix in _NONDETERMINISTIC_CALL_SUFFIXES:
        return "time"
    return _EXTERNAL_CALL_ROOTS.get(name.split(".", 1)[0])


class _LocalNameCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.names.add(node.id)


class _FunctionFacts(ast.NodeVisitor):
    """Collect facts from one function while ignoring nested definitions."""

    def __init__(self, argument_names: set[str], local_names: set[str]) -> None:
        self.argument_names = argument_names
        self.local_names = local_names | argument_names
        self.branches: list[dict[str, Any]] = []
        self.raises: list[dict[str, Any]] = []
        self.calls: set[str] = set()
        self.external_dependencies: set[str] = set()
        self.mutated_arguments: set[str] = set()
        self.nested_functions: list[str] = []
        self.parameter_attributes: set[str] = set()
        self.stateful_writes: set[str] = set()
        self.has_yield = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.nested_functions.append(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.nested_functions.append(node.name)

    def visit_If(self, node: ast.If) -> None:
        self.branches.append({"line": node.lineno, "condition": _unparse(node.test)})
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        self.branches.append({"line": node.lineno, "condition": "match statement"})
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        exc = None
        if node.exc is not None:
            exc = _unparse(node.exc.func) if isinstance(node.exc, ast.Call) else _unparse(node.exc)
        self.raises.append({"line": node.lineno, "exception": exc})
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node)
        if name:
            self.calls.add(name)
            category = _external_call_category(name)
            if category:
                self.external_dependencies.add(category)

        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            if node.func.value.id in self.argument_names and node.func.attr in {
                "append", "extend", "insert", "pop", "remove", "clear", "sort",
                "reverse", "update", "setdefault", "add", "discard",
            }:
                self.mutated_arguments.add(node.func.value.id)
            elif (
                node.func.value.id not in self.local_names
                and node.func.attr in _JSON_VALUE_ATTRIBUTES
            ):
                self.stateful_writes.add(f"{node.func.value.id}.{node.func.attr}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        root = node.value
        while isinstance(root, (ast.Attribute, ast.Subscript)):
            root = root.value
        if (
            isinstance(root, ast.Name)
            and root.id in self.argument_names
            and node.attr not in _JSON_VALUE_ATTRIBUTES
        ):
            self.parameter_attributes.add(f"{root.id}.{node.attr}")
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            root = _mutation_root(target)
            if root in self.argument_names:
                self.mutated_arguments.add(root)
            elif root and root not in self.local_names:
                self.stateful_writes.add(root)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        root = _mutation_root(node.target)
        if root in self.argument_names:
            self.mutated_arguments.add(root)
        elif root and root not in self.local_names:
            self.stateful_writes.add(root)
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        self.stateful_writes.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.stateful_writes.update(node.names)

    def visit_Yield(self, node: ast.Yield) -> None:
        self.has_yield = True
        self.generic_visit(node)

    def visit_YieldFrom(self, node: ast.YieldFrom) -> None:
        self.has_yield = True
        self.generic_visit(node)


def _mutation_root(node: ast.AST) -> str | None:
    while isinstance(node, (ast.Subscript, ast.Attribute)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _parameter_records(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[dict[str, Any]]:
    positional = list(node.args.posonlyargs) + list(node.args.args)
    default_offset = len(positional) - len(node.args.defaults)
    records: list[dict[str, Any]] = []

    for index, arg in enumerate(positional):
        default = node.args.defaults[index - default_offset] if index >= default_offset else None
        records.append({
            "name": arg.arg,
            "kind": "positional_only" if index < len(node.args.posonlyargs) else "positional_or_keyword",
            "annotation": _unparse(arg.annotation),
            "default": _unparse(default),
        })

    if node.args.vararg:
        records.append({
            "name": node.args.vararg.arg,
            "kind": "var_positional",
            "annotation": _unparse(node.args.vararg.annotation),
            "default": None,
        })

    for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
        records.append({
            "name": arg.arg,
            "kind": "keyword_only",
            "annotation": _unparse(arg.annotation),
            "default": _unparse(default),
        })

    if node.args.kwarg:
        records.append({
            "name": node.args.kwarg.arg,
            "kind": "var_keyword",
            "annotation": _unparse(node.args.kwarg.annotation),
            "default": None,
        })
    return records


def _function_record(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any]:
    parameters = _parameter_records(node)
    argument_names = {p["name"] for p in parameters}
    local_collector = _LocalNameCollector()
    for statement in node.body:
        local_collector.visit(statement)
    facts = _FunctionFacts(argument_names, local_collector.names)
    for statement in node.body:
        facts.visit(statement)

    docstring = ast.get_docstring(node)
    return {
        "name": node.name,
        "async": isinstance(node, ast.AsyncFunctionDef),
        "line": node.lineno,
        "parameters": parameters,
        "return_annotation": _unparse(node.returns),
        "docstring": docstring.splitlines()[0] if docstring else None,
        "branches": facts.branches,
        "raises": facts.raises,
        "calls": sorted(facts.calls),
        "external_dependencies": sorted(facts.external_dependencies),
        "mutated_arguments": sorted(facts.mutated_arguments),
        "nested_functions": facts.nested_functions,
        "parameter_attributes": sorted(facts.parameter_attributes),
        "stateful_writes": sorted(facts.stateful_writes),
        "generator": facts.has_yield,
    }


def _annotation_is_json_safe(annotation: str | None) -> bool:
    if not annotation:
        return True
    identifiers = {part.lower() for part in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", annotation)}
    identifiers.discard("typing")
    return bool(identifiers) and identifiers <= _JSON_SAFE_ANNOTATIONS


def _is_static_value(node: ast.AST) -> bool:
    """Accept constants and constant-only expressions without evaluating code."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_static_value(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            key is not None and _is_static_value(key) and _is_static_value(value)
            for key, value in zip(node.keys, node.values)
        )
    if isinstance(node, ast.UnaryOp):
        return isinstance(node.op, (ast.UAdd, ast.USub, ast.Invert, ast.Not)) and _is_static_value(node.operand)
    if isinstance(node, ast.BinOp):
        return isinstance(node.op, (
            ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
            ast.Pow, ast.LShift, ast.RShift, ast.BitOr, ast.BitAnd, ast.BitXor,
        )) and _is_static_value(node.left) and _is_static_value(node.right)
    return False


def assess_behavioral_eligibility(analysis: dict[str, Any]) -> dict[str, Any]:
    """Conservatively decide whether JSON behavioral probing is appropriate.

    Unknown annotations remain eligible only when the AST treats the parameter
    as a value/container. Attribute access on a parameter is considered an
    injected protocol or custom object and is routed to normal code generation.
    """
    reasons: list[str] = []
    if not analysis.get("valid"):
        reasons.append("source_is_not_valid_python")
    if analysis.get("classes"):
        reasons.append("module_contains_classes_or_custom_objects")
    if analysis.get("unsafe_imports"):
        reasons.append("module_has_external_imports")
    if analysis.get("top_level_side_effects"):
        reasons.append("module_has_top_level_side_effects")

    functions = analysis.get("functions", [])
    if not functions:
        reasons.append("module_has_no_top_level_functions")
    for function in functions:
        name = function.get("name", "<unknown>")
        if function.get("external_dependencies"):
            reasons.append(f"{name}:external_dependency")
        if function.get("parameter_attributes"):
            reasons.append(f"{name}:custom_object_or_injected_protocol")
        if function.get("stateful_writes"):
            reasons.append(f"{name}:shared_state_mutation")
        if function.get("generator"):
            reasons.append(f"{name}:generator_requires_consumption_strategy")
        for parameter in function.get("parameters", []):
            annotation = parameter.get("annotation")
            if annotation and not _annotation_is_json_safe(annotation):
                reasons.append(f"{name}:{parameter.get('name')}:non_json_annotation")

    return {"eligible": not reasons, "reasons": sorted(set(reasons))}


def analyze_python_source(source_code: str) -> dict[str, Any]:
    """Return a JSON-serialisable contract for a Python source file."""
    try:
        tree = ast.parse(source_code)
    except SyntaxError as exc:
        return {
            "valid": False,
            "error": f"SyntaxError at line {exc.lineno}: {exc.msg}",
            "functions": [],
            "classes": [],
            "top_level_symbols": [],
        }

    functions: list[dict[str, Any]] = []
    classes: list[dict[str, Any]] = []
    top_level_symbols: list[str] = []
    imports: list[str] = []
    unsafe_imports: list[str] = []
    top_level_side_effects: list[int] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(_function_record(node))
            top_level_symbols.append(node.name)
            evaluated_expressions = [
                *node.decorator_list,
                *node.args.defaults,
                *(default for default in node.args.kw_defaults if default is not None),
            ]
            if any(isinstance(child, ast.Call) for expr in evaluated_expressions for child in ast.walk(expr)):
                top_level_side_effects.append(node.lineno)
        elif isinstance(node, ast.ClassDef):
            methods = [
                _function_record(child)
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            classes.append({
                "name": node.name,
                "line": node.lineno,
                "bases": [_unparse(base) for base in node.bases],
                "methods": methods,
            })
            top_level_symbols.append(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            for name in names:
                root = name.split(".", 1)[0]
                if root:
                    imports.append(root)
                    if root not in _SAFE_IMPORT_ROOTS:
                        unsafe_imports.append(root)
        elif isinstance(node, ast.Assign):
            if not all(isinstance(target, ast.Name) for target in node.targets):
                top_level_side_effects.append(node.lineno)
            elif not _is_static_value(node.value):
                top_level_side_effects.append(node.lineno)
        elif isinstance(node, ast.AnnAssign):
            if node.value is not None and not _is_static_value(node.value):
                top_level_side_effects.append(node.lineno)
        elif not isinstance(node, (ast.Expr, ast.Pass)) or not (
            isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            top_level_side_effects.append(getattr(node, "lineno", 0))

    result = {
        "valid": True,
        "functions": functions,
        "classes": classes,
        "top_level_symbols": top_level_symbols,
        "imports": sorted(set(imports)),
        "unsafe_imports": sorted(set(unsafe_imports)),
        "top_level_side_effects": top_level_side_effects,
    }
    result["behavioral_eligibility"] = assess_behavioral_eligibility(result)
    return result
