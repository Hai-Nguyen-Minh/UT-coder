import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Mapping, Optional

from .base import Sandbox, SandboxResult

logger = logging.getLogger(__name__)

class CSharpSandbox(Sandbox):
    """Execution sandbox for C# (.NET) using xUnit, coverlet, and Stryker.NET."""

    def run_test(
        self,
        file_name: str,
        source_code: str,
        test_code: str,
        project_files: Mapping[str, str] | None = None,
    ) -> SandboxResult:
        # In .NET, it's easiest to create a fresh xunit project
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # 1. Initialize xunit project
            subprocess.run(
                ["dotnet", "new", "xunit"],
                cwd=temp_dir,
                capture_output=True,
                text=True
            )
            
            # Remove default UnitTest1.cs
            default_test = temp_path / "UnitTest1.cs"
            if default_test.exists():
                default_test.unlink()
                
            # 2. Add packages (Moq for mocking, coverlet for coverage)
            subprocess.run(["dotnet", "add", "package", "Moq"], cwd=temp_dir, capture_output=True)
            subprocess.run(["dotnet", "add", "package", "coverlet.msbuild"], cwd=temp_dir, capture_output=True)
            
            # 3. Write source and test files
            source_file = temp_path / "Source.cs"
            test_file = temp_path / "Tests.cs"
            
            source_file.write_text(source_code, encoding="utf-8")
            test_file.write_text(test_code, encoding="utf-8")
            
            # 4. Run tests with coverage
            test_cmd = [
                "dotnet", "test",
                "/p:CollectCoverage=true",
                "/p:CoverletOutputFormat=json"
            ]
            
            logger.info(f"Running dotnet test: {' '.join(test_cmd)}")
            
            process = subprocess.run(
                test_cmd,
                cwd=temp_dir,
                capture_output=True,
                text=True
            )
            
            stdout = process.stdout
            stderr = process.stderr
            success = process.returncode == 0
            
            error_log = ""
            if not success:
                error_log = stderr if stderr else stdout
                return SandboxResult(
                    success=False,
                    stdout=stdout,
                    stderr=stderr,
                    error_log=error_log
                )
                
            # 5. Extract coverage
            coverage_val = None
            cov_json_path = temp_path / "coverage.json"
            if cov_json_path.exists():
                try:
                    cov_data = json.loads(cov_json_path.read_text(encoding="utf-8"))
                    # coverlet json format: { "ProjectName": { "DocumentPath": { "Class": { "Method": { "Line": Hits } } } } }
                    # We approximate line coverage
                    total_lines = 0
                    covered_lines = 0
                    for proj, docs in cov_data.items():
                        for doc, classes in docs.items():
                            for cls, methods in classes.items():
                                for method, lines in methods.items():
                                    for line, hits in lines.items():
                                        total_lines += 1
                                        if hits > 0:
                                            covered_lines += 1
                    if total_lines > 0:
                        coverage_val = (covered_lines / total_lines) * 100.0
                    else:
                        coverage_val = 0.0
                except Exception as e:
                    logger.warning(f"Failed to parse coverlet coverage.json: {e}")
            return SandboxResult(
                success=True,
                stdout=stdout,
                stderr=stderr,
                error_log="",
                coverage=coverage_val
            )
