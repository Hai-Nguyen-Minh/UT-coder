from __future__ import annotations

import ast
import re
import textwrap


_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


def failed_pytest_targets(error_log: str) -> list[str]:
    """Extract qualified test nodes plus the hook responsible for setup errors."""
    targets: list[str] = []
    for line in error_log.splitlines():
        match = re.match(r"^(?:FAILED|ERROR)\s+(\S+)", line.strip())
        if not match:
            continue
        parts = match.group(1).split("::")[1:]
        if not parts:
            continue
        parts[-1] = parts[-1].split("[", 1)[0]
        targets.append("::".join(parts))
    for match in re.finditer(
        r"ERROR at (setup|teardown) of (?:(?P<class>[A-Za-z_]\w*)\.)?(?P<test>[A-Za-z_]\w*)",
        error_log,
    ):
        hook = (
            f"{match.group(1)}_method"
            if match.group("class")
            else f"{match.group(1)}_function"
        )
        targets.append(
            f"{match.group('class')}::{hook}" if match.group("class") else hook
        )
    seen: set[str] = set()
    return [
        target for target in targets
        if target and not (target in seen or seen.add(target))
    ]


def _normalise_target(value: str) -> str:
    parts = [part for part in str(value).split("::") if part]
    if parts and parts[0].endswith(".py"):
        parts = parts[1:]
    if parts:
        parts[-1] = parts[-1].split("[", 1)[0]
    return "::".join(parts)


def _source_segment(source_code: str, node: ast.AST) -> str:
    lines = source_code.splitlines()
    decorators = getattr(node, "decorator_list", [])
    start_line = min(
        [getattr(node, "lineno", 1), *(item.lineno for item in decorators)],
    )
    end_line = getattr(node, "end_lineno", start_line)
    return textwrap.dedent("\n".join(lines[start_line - 1:end_line]))


def extract_functions(source_code: str, function_names: list[str]) -> str:
    """Extract top-level tests or qualified ``Class::method`` pytest nodes."""
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return ""
    targets = {_normalise_target(name) for name in function_names}
    extracted: list[str] = []
    for node in tree.body:
        if isinstance(node, _FUNCTION_NODES) and node.name in targets:
            extracted.append(f"# pytest node: {node.name}\n{_source_segment(source_code, node)}")
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                key = f"{node.name}::{getattr(child, 'name', '')}"
                if isinstance(child, _FUNCTION_NODES) and key in targets:
                    extracted.append(f"# pytest node: {key}\n{_source_segment(source_code, child)}")
    return "\n\n".join(extracted)


def patch_functions(
    original_source: str,
    new_functions_source: str,
    function_names: list[str] | None = None,
) -> str:
    """Patch selected top-level tests or class methods with AST-safe replacements."""
    try:
        original_tree = ast.parse(original_source)
        new_tree = ast.parse(textwrap.dedent(new_functions_source))
    except SyntaxError:
        return original_source

    standalone: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    qualified: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in new_tree.body:
        if isinstance(node, _FUNCTION_NODES):
            standalone[node.name] = node
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, _FUNCTION_NODES):
                    qualified[f"{node.name}::{child.name}"] = child
    if not standalone and not qualified:
        return original_source

    targets = (
        {_normalise_target(name) for name in function_names}
        if function_names is not None
        else None
    )

    class FunctionPatcher(ast.NodeTransformer):
        def __init__(self) -> None:
            self.class_stack: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef):
            self.class_stack.append(node.name)
            node = self.generic_visit(node)
            self.class_stack.pop()
            return node

        def _replace(self, node):
            key = (
                f"{self.class_stack[-1]}::{node.name}"
                if self.class_stack
                else node.name
            )
            if targets is not None and key not in targets:
                return node
            replacement = qualified.get(key) or standalone.get(node.name)
            if replacement is None:
                return node
            if not replacement.decorator_list and node.decorator_list:
                replacement.decorator_list = node.decorator_list
            return ast.copy_location(replacement, node)

        def visit_FunctionDef(self, node: ast.FunctionDef):
            return self._replace(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
            return self._replace(node)

    patched_tree = FunctionPatcher().visit(original_tree)
    ast.fix_missing_locations(patched_tree)
    return ast.unparse(patched_tree) + "\n"
