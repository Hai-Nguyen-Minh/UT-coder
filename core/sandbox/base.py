import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Optional


MAX_PROJECT_FILES = 256
MAX_PROJECT_BYTES = 4 * 1024 * 1024


def normalize_project_files(
    project_files: Mapping[str, str] | None,
    *,
    reserved_paths: Iterable[str] = (),
) -> dict[str, str]:
    """Validate and normalize sandbox-relative project support files.

    Project paths are treated as POSIX-style paths on every host so that an
    ablation dataset behaves identically on Windows development machines and
    the Ubuntu evaluator.  The returned mapping is safe to materialize below a
    fresh sandbox root; absolute paths, parent traversal, collisions and
    file/directory prefix conflicts are rejected before any file is written.
    """

    if project_files is None:
        return {}
    if not isinstance(project_files, Mapping):
        raise TypeError("project_files must be a mapping of relative path to text")
    if len(project_files) > MAX_PROJECT_FILES:
        raise ValueError(
            f"project_files contains more than {MAX_PROJECT_FILES} files"
        )

    normalized: dict[str, str] = {}
    total_bytes = 0
    for raw_path, content in project_files.items():
        if not isinstance(raw_path, str) or not isinstance(content, str):
            raise TypeError("project_files paths and contents must be strings")
        portable = raw_path.replace("\\", "/")
        parts = portable.split("/")
        if (
            not portable
            or "\x00" in portable
            or portable.startswith("/")
            or re.match(r"^[A-Za-z]:", portable)
            or any(part in {"", ".", ".."} for part in parts)
            or any(":" in part for part in parts)
        ):
            raise ValueError(f"Unsafe project file path: {raw_path!r}")
        canonical = PurePosixPath(*parts).as_posix()
        if canonical in normalized:
            raise ValueError(f"Duplicate project file path: {canonical!r}")
        total_bytes += len(content.encode("utf-8"))
        if total_bytes > MAX_PROJECT_BYTES:
            raise ValueError(
                f"project_files exceeds the {MAX_PROJECT_BYTES}-byte limit"
            )
        normalized[canonical] = content

    paths = set(normalized)
    reserved = {
        PurePosixPath(str(path).replace("\\", "/")).as_posix()
        for path in reserved_paths
    }
    for canonical in paths:
        parents = {
            parent.as_posix()
            for parent in PurePosixPath(canonical).parents
            if parent.as_posix() != "."
        }
        if parents & paths:
            conflict = sorted(parents & paths)[0]
            raise ValueError(
                f"Project path {conflict!r} is both a file and a directory"
            )
        for protected in reserved:
            protected_parents = {
                parent.as_posix()
                for parent in PurePosixPath(protected).parents
                if parent.as_posix() != "."
            }
            if (
                canonical == protected
                or canonical in protected_parents
                or protected in parents
            ):
                raise ValueError(
                    f"Project file path collides with sandbox file: {canonical!r}"
                )
    return normalized


def write_project_files(
    root: Path,
    project_files: Mapping[str, str] | None,
    *,
    reserved_paths: Iterable[str] = (),
) -> dict[str, str]:
    """Materialize validated support files beneath ``root`` and return them."""

    normalized = normalize_project_files(
        project_files,
        reserved_paths=reserved_paths,
    )
    resolved_root = root.resolve()
    for relative_path, content in normalized.items():
        destination = root.joinpath(*PurePosixPath(relative_path).parts)
        resolved_destination = destination.resolve(strict=False)
        try:
            resolved_destination.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(f"Project file escapes sandbox: {relative_path!r}") from exc
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")

    if os.name == "posix":
        for directory in sorted(
            {path.parent for path in root.rglob("*") if path.is_file()},
            key=lambda path: len(path.parts),
        ):
            if directory == root or root in directory.parents:
                directory.chmod(0o777)
        for relative_path in normalized:
            root.joinpath(*PurePosixPath(relative_path).parts).chmod(0o666)
    return normalized


class SandboxInfrastructureError(RuntimeError):
    """The sandbox itself could not start; this is not a generated-test failure."""


def detect_sandbox_infrastructure_error(*logs: str) -> Optional[str]:
    """Return a stable diagnostic for known server-side sandbox failures."""
    text = "\n".join(str(log or "") for log in logs)
    lowered = text.lower()

    if "sandbox setup failed: required linux user" in lowered:
        return (
            "Dedicated Ubuntu sandbox user is missing. Rebuild the Docker image "
            "before running the benchmark."
        )
    if (
        "resource_runner.py" in lowered
        and "blockingioerror" in lowered
        and "resource temporarily unavailable" in lowered
    ):
        return (
            "Ubuntu rejected sandbox exec() because the process UID exhausted "
            "RLIMIT_NPROC. Rebuild with the dedicated sandbox user."
        )
    if "no module named pytest" in lowered or "no module named 'pytest'" in lowered:
        return "The server image does not contain pytest. Rebuild the Docker image."
    if "no module named pytest_cov" in lowered or "no module named 'pytest_cov'" in lowered:
        return "The server image does not contain pytest-cov. Rebuild the Docker image."
    if "could not start mutmut" in lowered or (
        "mutmut" in lowered and "no such file or directory" in lowered
    ):
        return "The server image does not contain mutmut. Rebuild the Docker image."
    if "resource_runner.py" in lowered and (
        "no such file or directory" in lowered or "permission denied" in lowered
    ):
        return "The sandbox resource runner is missing or inaccessible in the server image."
    return None

@dataclass
class SandboxResult:
    """Result of running a unit test in the sandbox."""
    success: bool
    stdout: str
    stderr: str
    error_log: str = ""
    coverage: Optional[float] = None
    missing_lines: list[int] = field(default_factory=list)
    execution_status: str = "unknown"
    coverage_valid: bool = False
    tests_collected: Optional[int] = None
    tests_passed: Optional[int] = None
    tests_failed: Optional[int] = None


class Sandbox:
    """Abstract base class for all language sandboxes."""

    def run_test(
        self,
        file_name: str,
        source_code: str,
        test_code: str,
        project_files: Mapping[str, str] | None = None,
    ) -> SandboxResult:
        """
        Executes the test code against the source code in an isolated environment.
        
        Args:
            file_name: The name of the original source file.
            source_code: The code of the module being tested.
            test_code: The generated unit test code.
            project_files: Optional sandbox-relative support files.
            
        Returns:
            SandboxResult object with the execution status and metrics.
        """
        return SandboxResult(
            success=False,
            stdout="",
            stderr="Sandbox not implemented for this language.",
            error_log="Sandbox not implemented for this language."
        )
