"""Deterministic normalization of common small-model pytest mistakes."""

from __future__ import annotations

import ast
import builtins

from core.source_analyzer import analyze_python_source


_SAFE_IMPORT_ROOTS = {
    "abc", "asyncio", "collections", "contextlib", "copy", "dataclasses",
    "datetime", "decimal", "enum", "functools", "io", "itertools", "json",
    "math", "os", "pathlib", "pytest", "re", "statistics", "sys", "time",
    "typing", "unittest",
}


class _PytestTransformer(ast.NodeTransformer):
    def visit_ImportFrom(self, node: ast.ImportFrom):
        node = self.generic_visit(node)
        if not node.module:
            return node
        root = node.module.split(".", 1)[0]
        if root not in _SAFE_IMPORT_ROOTS and root not in self.source_import_roots and any(
            alias.name in self.top_level_symbols for alias in node.names
        ):
            node.module = "module_under_test"
            node.level = 0
            node.names = [alias for alias in node.names if alias.name in self.top_level_symbols]
            return node if node.names else None
        return node

    def visit_Import(self, node: ast.Import):
        node = self.generic_visit(node)
        for alias in node.names:
            root = alias.name.split(".", 1)[0]
            bound_name = alias.asname or root
            if (
                root not in _SAFE_IMPORT_ROOTS
                and root not in self.source_import_roots
                and alias.name != "module_under_test"
                and bound_name in self.module_alias_candidates
            ):
                alias.name = "module_under_test"
        return node

    def visit_Expr(self, node: ast.Expr):
        node = self.generic_visit(node)
        if not isinstance(node.value, ast.Call):
            return node
        call = node.value
        if not (
            isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "self"
        ):
            return node

        method = call.func.attr
        args = call.args
        if method in {"assertEqual", "assertListEqual", "assertTupleEqual", "assertDictEqual", "assertSetEqual"} and len(args) >= 2:
            return ast.Assert(test=ast.Compare(left=args[0], ops=[ast.Eq()], comparators=[args[1]]))
        if method == "assertNotEqual" and len(args) >= 2:
            return ast.Assert(test=ast.Compare(left=args[0], ops=[ast.NotEq()], comparators=[args[1]]))
        if method == "assertTrue" and args:
            return ast.Assert(test=args[0])
        if method == "assertFalse" and args:
            return ast.Assert(test=ast.UnaryOp(op=ast.Not(), operand=args[0]))
        if method == "assertIsNone" and args:
            return ast.Assert(test=ast.Compare(left=args[0], ops=[ast.Is()], comparators=[ast.Constant(None)]))
        if method == "assertIsNotNone" and args:
            return ast.Assert(test=ast.Compare(left=args[0], ops=[ast.IsNot()], comparators=[ast.Constant(None)]))
        if method == "assertIn" and len(args) >= 2:
            return ast.Assert(test=ast.Compare(left=args[0], ops=[ast.In()], comparators=[args[1]]))
        if method == "assertNotIn" and len(args) >= 2:
            return ast.Assert(test=ast.Compare(left=args[0], ops=[ast.NotIn()], comparators=[args[1]]))
        if method == "assertIs" and len(args) >= 2:
            return ast.Assert(test=ast.Compare(left=args[0], ops=[ast.Is()], comparators=[args[1]]))
        if method == "assertIsNot" and len(args) >= 2:
            return ast.Assert(test=ast.Compare(left=args[0], ops=[ast.IsNot()], comparators=[args[1]]))
        comparison_methods = {
            "assertGreater": ast.Gt,
            "assertGreaterEqual": ast.GtE,
            "assertLess": ast.Lt,
            "assertLessEqual": ast.LtE,
        }
        if method in comparison_methods and len(args) >= 2:
            return ast.Assert(
                test=ast.Compare(left=args[0], ops=[comparison_methods[method]()], comparators=[args[1]])
            )
        if method == "assertAlmostEqual" and len(args) >= 2:
            approximate = ast.Call(
                func=ast.Attribute(value=ast.Name(id="pytest", ctx=ast.Load()), attr="approx", ctx=ast.Load()),
                args=[args[1]],
                keywords=[],
            )
            return ast.Assert(test=ast.Compare(left=args[0], ops=[ast.Eq()], comparators=[approximate]))
        if method == "assertIsInstance" and len(args) >= 2:
            instance_check = ast.Call(
                func=ast.Name(id="isinstance", ctx=ast.Load()),
                args=[args[0], args[1]],
                keywords=[],
            )
            return ast.Assert(test=instance_check)
        if method == "assertCountEqual" and len(args) >= 2:
            def sorted_by_repr(value: ast.AST) -> ast.Call:
                return ast.Call(
                    func=ast.Name(id="sorted", ctx=ast.Load()),
                    args=[value],
                    keywords=[ast.keyword(arg="key", value=ast.Name(id="repr", ctx=ast.Load()))],
                )

            return ast.Assert(
                test=ast.Compare(
                    left=sorted_by_repr(args[0]),
                    ops=[ast.Eq()],
                    comparators=[sorted_by_repr(args[1])],
                )
            )
        if method == "assertRegex" and len(args) >= 2:
            regex_check = ast.Call(
                func=ast.Attribute(value=ast.Name(id="re", ctx=ast.Load()), attr="search", ctx=ast.Load()),
                args=[args[1], args[0]],
                keywords=[],
            )
            return ast.Assert(test=regex_check)
        if method == "assertRaises" and len(args) >= 2:
            raised_call = ast.Call(func=args[1], args=args[2:], keywords=call.keywords)
            context = ast.Call(
                func=ast.Attribute(value=ast.Name(id="pytest", ctx=ast.Load()), attr="raises", ctx=ast.Load()),
                args=[args[0]],
                keywords=[],
            )
            return ast.With(items=[ast.withitem(context_expr=context)], body=[ast.Expr(value=raised_call)])
        return node

    def visit_With(self, node: ast.With):
        node = self.generic_visit(node)
        for item in node.items:
            call = item.context_expr
            if not (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "self"
                and call.func.attr in {"assertRaises", "assertRaisesRegex"}
                and call.args
            ):
                continue
            keywords = []
            if call.func.attr == "assertRaisesRegex" and len(call.args) >= 2:
                keywords.append(ast.keyword(arg="match", value=call.args[1]))
            item.context_expr = ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="pytest", ctx=ast.Load()),
                    attr="raises",
                    ctx=ast.Load(),
                ),
                args=[call.args[0]],
                keywords=keywords,
            )
        return node

    def __init__(
        self,
        top_level_symbols: set[str],
        module_alias_candidates: set[str],
        source_import_roots: set[str],
    ) -> None:
        self.top_level_symbols = top_level_symbols
        self.module_alias_candidates = module_alias_candidates
        self.source_import_roots = source_import_roots


def _import_insertion_index(tree: ast.Module) -> int:
    index = 0
    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        index = 1
    while (
        index < len(tree.body)
        and isinstance(tree.body[index], ast.ImportFrom)
        and tree.body[index].module == "__future__"
    ):
        index += 1
    return index


def _ensure_pytest_import(tree: ast.Module) -> None:
    has_pytest = any(
        isinstance(node, ast.Import) and any(alias.name == "pytest" for alias in node.names)
        for node in tree.body
    )
    if has_pytest:
        return
    tree.body.insert(_import_insertion_index(tree), ast.Import(names=[ast.alias(name="pytest")]))


def _ensure_import(tree: ast.Module, module_name: str) -> None:
    if any(
        isinstance(node, ast.Import) and any(alias.name == module_name for alias in node.names)
        for node in tree.body
    ):
        return
    tree.body.insert(_import_insertion_index(tree), ast.Import(names=[ast.alias(name=module_name)]))


def _ensure_from_import(tree: ast.Module, module_name: str, symbol: str) -> None:
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == module_name:
            if any((alias.asname or alias.name) == symbol for alias in node.names):
                return
            node.names.append(ast.alias(name=symbol))
            return
    tree.body.insert(
        _import_insertion_index(tree),
        ast.ImportFrom(module=module_name, names=[ast.alias(name=symbol)], level=0),
    )


def _bound_names(tree: ast.Module) -> set[str]:
    names = set(dir(builtins))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.asname or alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names if alias.name != "*")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.update(arg.arg for arg in [
                    *node.args.posonlyargs,
                    *node.args.args,
                    *node.args.kwonlyargs,
                ])
                if node.args.vararg:
                    names.add(node.args.vararg.arg)
                if node.args.kwarg:
                    names.add(node.args.kwarg.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Param)):
            names.add(node.id)
    return names


def _repair_safe_missing_imports(tree: ast.Module, protected_names: set[str]) -> None:
    """Add only deterministic stdlib/test helpers that are visibly unbound."""
    loaded = {
        node.id for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    missing = loaded - _bound_names(tree) - protected_names
    direct_modules = {"csv", "io", "json", "pathlib"}
    from_imports = {
        "BytesIO": ("io", "BytesIO"),
        "StringIO": ("io", "StringIO"),
        "date": ("datetime", "date"),
        "timedelta": ("datetime", "timedelta"),
        "Decimal": ("decimal", "Decimal"),
        "Path": ("pathlib", "Path"),
        "MagicMock": ("unittest.mock", "MagicMock"),
        "Mock": ("unittest.mock", "Mock"),
        "mock": ("unittest", "mock"),
        "patch": ("unittest.mock", "patch"),
    }
    for module_name in sorted(missing & direct_modules):
        _ensure_import(tree, module_name)
    if "datetime" in missing:
        module_style = any(
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "datetime"
            and node.attr in {"date", "datetime", "timedelta", "timezone"}
            for node in ast.walk(tree)
        )
        if module_style:
            _ensure_import(tree, "datetime")
        else:
            _ensure_from_import(tree, "datetime", "datetime")
    for name in sorted(missing & from_imports.keys()):
        module_name, symbol = from_imports[name]
        _ensure_from_import(tree, module_name, symbol)


class _RagStyleTransformer(ast.NodeTransformer):
    """Convert verified unittest examples into concise pytest demonstrations."""

    def __init__(self, top_level_symbols: list[str]) -> None:
        self.top_level_symbols = top_level_symbols

    def visit_ClassDef(self, node: ast.ClassDef):
        node = self.generic_visit(node)
        node.bases = [
            base for base in node.bases
            if ast.unparse(base) not in {"unittest.TestCase", "TestCase"}
        ]
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                child.name = {
                    "setUp": "setup_method",
                    "tearDown": "teardown_method",
                    "setUpClass": "setup_class",
                    "tearDownClass": "teardown_class",
                }.get(child.name, child.name)
        return node

    def visit_ImportFrom(self, node: ast.ImportFrom):
        node = self.generic_visit(node)
        if node.module == "module_under_test" and any(alias.name == "*" for alias in node.names):
            node.names = [ast.alias(name=name) for name in self.top_level_symbols]
            return node if node.names else None
        if node.module == "unittest":
            node.names = [alias for alias in node.names if alias.name != "TestCase"]
            return node if node.names else None
        return node

    def visit_If(self, node: ast.If):
        if (
            isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
        ):
            return None
        return self.generic_visit(node)


def normalize_python_tests(test_code: str, source_code: str) -> str:
    """Normalize imports and unittest-style assertions; return original on syntax error."""
    analysis = analyze_python_source(source_code)
    top_level = set(analysis.get("top_level_symbols", []))
    source_import_roots = set(analysis.get("imports", []))
    try:
        tree = ast.parse(test_code)
    except SyntaxError:
        return test_code

    module_alias_candidates = {
        node.value.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr in top_level
        and isinstance(node.value, ast.Name)
    }
    tree = _PytestTransformer(top_level, module_alias_candidates, source_import_roots).visit(tree)
    _repair_safe_missing_imports(tree, top_level)
    if any(
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "re"
        for node in ast.walk(tree)
    ):
        _ensure_import(tree, "re")
    _ensure_pytest_import(tree)
    ast.fix_missing_locations(tree)
    try:
        return ast.unparse(tree) + "\n"
    except Exception:
        return test_code


def normalize_rag_example(test_code: str, source_code: str) -> str:
    """Create pytest-style few-shot text without replacing verified ground truth."""
    normalized = normalize_python_tests(test_code, source_code)
    analysis = analyze_python_source(source_code)
    top_level = list(analysis.get("top_level_symbols", []))
    try:
        tree = ast.parse(normalized)
    except SyntaxError:
        return normalized

    tree = _RagStyleTransformer(top_level).visit(tree)
    uses_unittest = any(
        isinstance(node, ast.Name) and node.id == "unittest"
        for node in ast.walk(tree)
    )
    if not uses_unittest:
        new_body: list[ast.stmt] = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                node.names = [alias for alias in node.names if alias.name != "unittest"]
                if not node.names:
                    continue
            new_body.append(node)
        tree.body = new_body

    if any(
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "re"
        for node in ast.walk(tree)
    ):
        _ensure_import(tree, "re")
    _ensure_pytest_import(tree)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n"
