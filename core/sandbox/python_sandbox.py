from __future__ import annotations

import ast
import json
import logging
import os
import re
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping

from .base import (
    Sandbox,
    SandboxResult,
    normalize_project_files,
    write_project_files,
)
from .resource_limits import run_limited_process

logger = logging.getLogger(__name__)


def _combined_log(stdout: str, stderr: str) -> str:
    return "\n\n".join(part for part in (stdout.strip(), stderr.strip()) if part)


def _pytest_execution_status(returncode: int, output: str) -> str:
    if returncode == 0:
        return "tests_passed"
    if returncode == 1:
        return "tests_failed"
    if returncode == 5:
        return "no_tests_collected"
    if returncode < 0:
        return "process_crash"
    lowered = output.lower()
    if "error collecting" in lowered or "errors during collection" in lowered:
        return "collection_error"
    if returncode == 2:
        return "pytest_interrupted"
    if returncode == 3:
        return "pytest_internal_error"
    if returncode == 4:
        return "pytest_usage_error"
    return "pytest_error"


def _junit_counts(path: Path) -> tuple[int | None, int | None, int | None]:
    if not path.exists():
        return None, None, None
    try:
        root = ET.parse(path).getroot()
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        if not suites:
            return None, None, None
        # A testsuites root contains aggregate attributes and child suites. Use
        # the root aggregate when present to avoid counting values twice.
        if root.tag == "testsuites" and root.get("tests") is not None:
            suites = [root]
        collected = sum(int(suite.get("tests", "0")) for suite in suites)
        failures = sum(int(suite.get("failures", "0")) for suite in suites)
        errors = sum(int(suite.get("errors", "0")) for suite in suites)
        skipped = sum(int(suite.get("skipped", "0")) for suite in suites)
        failed = failures + errors
        passed = max(0, collected - failed - skipped)
        return collected, passed, failed
    except (ET.ParseError, OSError, TypeError, ValueError) as exc:
        logger.warning("Failed to read pytest JUnit report %s: %s", path.name, exc)
        return None, None, None


def _read_current_coverage(
    path: Path,
    *,
    module_name: str,
    started_ns: int,
    execution_status: str,
) -> tuple[float | None, list[int], bool]:
    if execution_status not in {"tests_passed", "tests_failed"} or not path.exists():
        return None, [], False
    try:
        # The file is unique per execution and was unlinked immediately before
        # pytest. The mtime check additionally prevents reuse on fast retry.
        if path.stat().st_mtime_ns < started_ns:
            return None, [], False
        data = json.loads(path.read_text(encoding="utf-8"))
        files = data.get("files", {})
        module_key = next(
            (
                key for key in files
                if Path(key).name == f"{module_name}.py"
            ),
            None,
        )
        if module_key is None:
            return None, [], False
        coverage = data.get("totals", {}).get("percent_covered")
        if not isinstance(coverage, (int, float)):
            return None, [], False
        missing = files[module_key].get("missing_lines", [])
        missing_lines = [line for line in missing if isinstance(line, int)]
        return float(coverage), missing_lines, True
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read current coverage report %s: %s", path.name, exc)
        return None, [], False


def _last_python_frame(output: str) -> tuple[str, int] | None:
    frames: list[tuple[int, str, int]] = []
    for match in re.finditer(
        r'File\s+["\'](?P<path>[^"\']+\.py)["\']\s*,\s*line\s+(?P<line>\d+)',
        output,
    ):
        frames.append((match.start(), match.group("path"), int(match.group("line"))))
    for match in re.finditer(
        r"(?m)^(?P<path>[^\r\n]*?\.py):(?P<line>\d+):(?:\s|$)",
        output,
    ):
        frames.append((match.start(), match.group("path").strip(), int(match.group("line"))))
    if not frames:
        return None
    _, path, line = max(frames, key=lambda item: item[0])
    return path, line


def _missing_file_from_error(output: str) -> str | None:
    patterns = (
        r"No such file or directory:\s*(?P<path>'(?:\\.|[^'])*'|\"(?:\\.|[^\"])*\")",
        r"cannot find the path specified:\s*(?P<path>'(?:\\.|[^'])*'|\"(?:\\.|[^\"])*\")",
    )
    matches: list[tuple[int, str]] = []
    for pattern in patterns:
        matches.extend(
            (match.start(), match.group("path"))
            for match in re.finditer(pattern, output, flags=re.IGNORECASE)
        )
    if not matches:
        return None
    _, literal = max(matches, key=lambda item: item[0])
    try:
        value = ast.literal_eval(literal)
    except (SyntaxError, ValueError):
        return None
    return value if isinstance(value, str) and value else None


def _call_is_write_open(call: ast.Call) -> bool:
    mode_node: ast.AST | None = None
    if isinstance(call.func, ast.Name) and call.func.id == "open":
        mode_node = call.args[1] if len(call.args) > 1 else None
    elif (
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "open"
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "builtins"
    ):
        mode_node = call.args[1] if len(call.args) > 1 else None
    elif isinstance(call.func, ast.Attribute) and call.func.attr == "open":
        # pathlib.Path.open(mode, ...) receives the mode as its first argument.
        mode_node = call.args[0] if call.args else None
    else:
        return False
    for keyword in call.keywords:
        if keyword.arg == "mode":
            mode_node = keyword.value
            break
    if not isinstance(mode_node, ast.Constant) or not isinstance(mode_node.value, str):
        return False
    return any(flag in mode_node.value for flag in ("w", "a", "x"))


def _test_line_uses_write_open(test_code: str, line: int) -> bool:
    try:
        tree = ast.parse(test_code)
    except SyntaxError:
        return False
    return any(
        isinstance(node, ast.Call)
        and node.lineno <= line <= getattr(node, "end_lineno", node.lineno)
        and _call_is_write_open(node)
        for node in ast.walk(tree)
    )


def _safe_missing_parent(
    temp_path: Path,
    *,
    test_file_name: str,
    test_code: str,
    output: str,
) -> Path | None:
    missing = _missing_file_from_error(output)
    frame = _last_python_frame(output)
    if missing is None or frame is None:
        return None
    frame_path, line = frame
    if Path(frame_path).name != test_file_name or not _test_line_uses_write_open(test_code, line):
        return None
    if (
        "\x00" in missing
        or re.match(r"^[A-Za-z]:[\\/]", missing)
        or missing.startswith(("/", "\\", "//"))
    ):
        return None
    relative = Path(missing)
    if ".." in relative.parts:
        return None
    root = temp_path.resolve()
    candidate = (root / relative).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    parent = candidate.parent
    if parent == root or parent.exists():
        return None
    return parent


class PythonSandbox(Sandbox):
    """Execute Python tests with bounded resources and explicit result states."""

    def run_test(
        self,
        file_name: str,
        source_code: str,
        test_code: str,
        project_files: Mapping[str, str] | None = None,
    ) -> SandboxResult:
        module_name = "module_under_test"
        test_file_name = f"test_{module_name}.py"
        reserved_paths = {
            f"{module_name}.py",
            test_file_name,
            "__init__.py",
        }
        project_files = normalize_project_files(
            project_files,
            reserved_paths=reserved_paths,
        )

        original_stem = Path(file_name).stem
        if original_stem != module_name:
            test_code = re.sub(
                rf"(?m)^(?P<indent>[ \t]*)from[ \t]+{re.escape(original_stem)}[ \t]+import",
                rf"\g<indent>from {module_name} import",
                test_code,
            )
            test_code = re.sub(
                rf"(?m)^(?P<indent>[ \t]*)import[ \t]+{re.escape(original_stem)}\b",
                rf"\g<indent>import {module_name}",
                test_code,
            )

        from core.test_normalizer import normalize_python_tests

        test_code = normalize_python_tests(test_code, source_code)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            if os.name == "posix":
                temp_path.chmod(0o777)
            source_path = temp_path / f"{module_name}.py"
            test_path = temp_path / test_file_name
            source_path.write_text(source_code, encoding="utf-8")
            test_path.write_text(test_code, encoding="utf-8")
            (temp_path / "__init__.py").write_text("", encoding="utf-8")
            write_project_files(
                temp_path,
                project_files,
                reserved_paths=reserved_paths,
            )

            base_env = {
                **os.environ,
                "PYTHONPATH": temp_dir,
                "HOME": temp_dir,
                # The resource wrapper starts as root and then drops to the
                # dedicated sandbox UID. PYTHONPYCACHEPREFIX would let the
                # root phase create parent directories that the child cannot
                # write on Ubuntu. Disable incidental bytecode instead;
                # `python -m py_compile` still performs the explicit compile
                # into the sandbox-owned temporary __pycache__ directory.
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "TZ": "UTC",
            }
            support_python_files = sorted(
                path for path in project_files if path.endswith(".py")
            )
            compile_cmd = [
                os.sys.executable,
                "-m",
                "py_compile",
                source_path.name,
                test_path.name,
                *support_python_files,
            ]
            try:
                compiled = run_limited_process(
                    compile_cmd,
                    cwd=temp_dir,
                    env=base_env,
                    timeout=10,
                    memory_mb=384,
                    cpu_seconds=8,
                    file_size_mb=8,
                    max_files=64,
                    max_processes=8,
                )
            except subprocess.TimeoutExpired as exc:
                stdout = str(exc.stdout or "")
                stderr = str(exc.stderr or "Py_compile timed out.")
                return SandboxResult(
                    success=False,
                    stdout=stdout,
                    stderr=stderr,
                    error_log=_combined_log(stdout, stderr),
                    execution_status="compile_timeout",
                )
            if compiled.returncode != 0:
                output = _combined_log(compiled.stdout, compiled.stderr)
                status = (
                    "test_compile_error"
                    if test_path.name in output
                    else "source_compile_error"
                )
                return SandboxResult(
                    success=False,
                    stdout=compiled.stdout,
                    stderr=compiled.stderr,
                    error_log=output,
                    execution_status=status,
                )

            def execute(run_number: int) -> dict[str, Any]:
                coverage_path = temp_path / f"coverage_{run_number}.json"
                coverage_data_path = temp_path / f".coverage_{run_number}"
                junit_path = temp_path / f"pytest_{run_number}.xml"
                for artifact in (coverage_path, coverage_data_path, junit_path):
                    artifact.unlink(missing_ok=True)
                pytest_cmd = [
                    os.sys.executable,
                    "-m",
                    "pytest",
                    test_file_name,
                    f"--cov={module_name}",
                    f"--cov-report=json:{coverage_path.name}",
                    f"--junitxml={junit_path.name}",
                    "--disable-warnings",
                    "-p",
                    "pytest_cov.plugin",
                    "-p",
                    "no:cacheprovider",
                    "--tb=short",
                    "-vv",
                ]
                logger.info("Running pytest: %s", " ".join(pytest_cmd))
                started_ns = time.time_ns()
                try:
                    process = run_limited_process(
                        pytest_cmd,
                        cwd=temp_dir,
                        env={**base_env, "COVERAGE_FILE": str(coverage_data_path)},
                        timeout=30,
                        memory_mb=768,
                        cpu_seconds=24,
                        file_size_mb=16,
                        max_files=128,
                        max_processes=24,
                    )
                    stdout = process.stdout
                    stderr = process.stderr
                    error_log = _combined_log(stdout, stderr)
                    status = _pytest_execution_status(process.returncode, error_log)
                except subprocess.TimeoutExpired as exc:
                    stdout = str(exc.stdout or "")
                    stderr = str(
                        exc.stderr or "Pytest execution timed out (infinite loop?)."
                    )
                    error_log = _combined_log(stdout, stderr)
                    status = "timeout"
                coverage, missing_lines, coverage_valid = _read_current_coverage(
                    coverage_path,
                    module_name=module_name,
                    started_ns=started_ns,
                    execution_status=status,
                )
                collected, passed, failed = _junit_counts(junit_path)
                return {
                    "stdout": stdout,
                    "stderr": stderr,
                    "error_log": error_log,
                    "status": status,
                    "coverage": coverage,
                    "missing_lines": missing_lines,
                    "coverage_valid": coverage_valid,
                    "tests_collected": collected,
                    "tests_passed": passed,
                    "tests_failed": failed,
                }

            outcome = execute(1)
            if outcome["status"] == "tests_failed":
                parent = _safe_missing_parent(
                    temp_path,
                    test_file_name=test_file_name,
                    test_code=test_code,
                    output=outcome["error_log"],
                )
                if parent is not None:
                    parent.mkdir(parents=True, exist_ok=True)
                    if os.name == "posix":
                        current = parent
                        root = temp_path.resolve()
                        while current != root:
                            current.chmod(0o777)
                            current = current.parent
                    logger.info(
                        "Fast retry after creating sandbox-contained test directory: %s",
                        parent.relative_to(temp_path),
                    )
                    outcome = execute(2)

            success = outcome["status"] == "tests_passed"
            return SandboxResult(
                success=success,
                stdout=outcome["stdout"],
                stderr=outcome["stderr"],
                error_log="" if success else outcome["error_log"],
                coverage=outcome["coverage"],
                missing_lines=outcome["missing_lines"],
                execution_status=outcome["status"],
                coverage_valid=outcome["coverage_valid"],
                tests_collected=outcome["tests_collected"],
                tests_passed=outcome["tests_passed"],
                tests_failed=outcome["tests_failed"],
            )
