from dataclasses import dataclass, field
from typing import Optional

@dataclass
class SandboxResult:
    """Result of running a unit test in the sandbox."""
    success: bool
    stdout: str
    stderr: str
    error_log: str = ""
    coverage: Optional[float] = None
    mutation_score: Optional[float] = None
    missing_lines: list[int] = field(default_factory=list)


class Sandbox:
    """Abstract base class for all language sandboxes."""

    def run_test(self, file_name: str, source_code: str, test_code: str) -> SandboxResult:
        """
        Executes the test code against the source code in an isolated environment.
        
        Args:
            file_name: The name of the original source file.
            source_code: The code of the module being tested.
            test_code: The generated unit test code.
            
        Returns:
            SandboxResult object with the execution status and metrics.
        """
        return SandboxResult(
            success=False,
            stdout="",
            stderr="Sandbox not implemented for this language.",
            error_log="Sandbox not implemented for this language."
        )
