import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from .base import Sandbox, SandboxResult

logger = logging.getLogger(__name__)

class PythonSandbox(Sandbox):
    """Execution sandbox for Python using pytest, pytest-cov, and mutmut."""

    def run_test(self, file_name: str, source_code: str, test_code: str) -> SandboxResult:
        module_name = "module_under_test"
        test_file_name = f"test_{module_name}.py"

        # ---- Auto-fix #1: Rewrite wrong module imports ----
        original_stem = Path(file_name).stem
        if original_stem != module_name:
            # Replace 'from <original> import ...'
            test_code = re.sub(
                rf"from\s+{re.escape(original_stem)}\s+import",
                f"from {module_name} import",
                test_code,
            )
            # Replace 'import <original>'
            test_code = re.sub(
                rf"import\s+{re.escape(original_stem)}\b",
                f"import {module_name}",
                test_code,
            )
        
        # Also catch common AI mistakes: 'from test import', 'from main import', etc.
        test_code = re.sub(
            r"from\s+(?!module_under_test|unittest|pytest|typing|collections|functools|os|sys|io|math|re|json|datetime|pathlib|abc|dataclasses|enum|copy|itertools|contextlib|mock)\w+\s+import",
            f"from {module_name} import",
            test_code,
        )

        # ---- Auto-fix #2: Inject 'import pytest' if missing ----
        if "import pytest" not in test_code:
            test_code = "import pytest\n" + test_code

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_path = temp_path / f"{module_name}.py"
            test_path = temp_path / test_file_name

            source_path.write_text(source_code, encoding="utf-8")
            test_path.write_text(test_code, encoding="utf-8")

            # Create an empty __init__.py so pytest can resolve modules easily if needed
            (temp_path / "__init__.py").write_text("")

            # 1. Run Pytest with Coverage
            pytest_cmd = [
                "pytest",
                str(test_file_name),
                f"--cov={module_name}",
                "--cov-report=json",
                "--disable-warnings"
            ]

            logger.info(f"Running pytest: {' '.join(pytest_cmd)}")
            
            # Use subprocess to run
            process = subprocess.run(
                pytest_cmd,
                cwd=temp_dir,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": temp_dir}
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

            # Extract coverage
            coverage_val = None
            missing_lines = []
            cov_json_path = temp_path / "coverage.json"
            if cov_json_path.exists():
                try:
                    cov_data = json.loads(cov_json_path.read_text(encoding="utf-8"))
                    coverage_val = cov_data.get("totals", {}).get("percent_covered", 0.0)
                    
                    # Extract missing lines for the module
                    files = cov_data.get("files", {})
                    module_cov = files.get(f"{module_name}.py", {})
                    missing_lines = module_cov.get("missing_lines", [])
                except Exception as e:
                    logger.warning(f"Failed to read coverage.json: {e}")

            # 2. Run Mutation Testing with mutmut
            # Write setup.cfg for mutmut to understand what to mutate
            setup_cfg_content = f"""[mutmut]
paths_to_mutate={module_name}.py
runner=python -m pytest {test_file_name} -q
"""
            (temp_path / "setup.cfg").write_text(setup_cfg_content, encoding="utf-8")

            mutmut_cmd = [
                "mutmut",
                "run"
            ]
            
            logger.info("Running mutmut...")
            mutmut_process = subprocess.run(
                mutmut_cmd,
                cwd=temp_dir,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONPATH": temp_dir}
            )
            
            mut_stdout = mutmut_process.stdout
            mutation_score = self._extract_mutation_score(mut_stdout)

            return SandboxResult(
                success=True,
                stdout=stdout + "\n" + mut_stdout,
                stderr=stderr + "\n" + mutmut_process.stderr,
                error_log="",
                coverage=coverage_val,
                mutation_score=mutation_score,
                missing_lines=missing_lines
            )

    def _extract_mutation_score(self, mutmut_output: str) -> Optional[float]:
        """Parse mutmut output to calculate mutation score."""
        # mutmut output format typically includes: 
        # - Killed: 10
        # - Survived: 2
        killed = 0
        survived = 0
        
        killed_match = re.search(r"Killed:\s*(\d+)", mutmut_output, re.IGNORECASE)
        if killed_match:
            killed = int(killed_match.group(1))
            
        survived_match = re.search(r"Survived:\s*(\d+)", mutmut_output, re.IGNORECASE)
        if survived_match:
            survived = int(survived_match.group(1))
            
        total = killed + survived
        if total == 0:
            return None
            
        return (killed / total) * 100.0
