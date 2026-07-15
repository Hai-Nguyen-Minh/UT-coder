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

PACKAGE_JSON = """{
  "name": "js-sandbox",
  "version": "1.0.0",
  "scripts": {
    "test": "jest",
    "stryker": "stryker run"
  },
  "devDependencies": {
    "jest": "^29.7.0",
    "@stryker-mutator/core": "^8.2.6",
    "@stryker-mutator/jest-runner": "^8.2.6"
  }
}
"""

STRYKER_CONF = """module.exports = {
  mutator: "javascript",
  packageManager: "npm",
  reporters: ["clear-text", "progress"],
  testRunner: "jest",
  coverageAnalysis: "perTest",
  mutate: [
    "*.js",
    "!*.test.js",
    "!jest.config.js",
    "!stryker.config.js"
  ]
};
"""

class JavascriptSandbox(Sandbox):
    """Execution sandbox for JavaScript using Jest and Stryker."""

    def run_test(self, file_name: str, source_code: str, test_code: str) -> SandboxResult:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # 1. Setup files
            (temp_path / "package.json").write_text(PACKAGE_JSON, encoding="utf-8")
            (temp_path / "stryker.config.js").write_text(STRYKER_CONF, encoding="utf-8")
            
            # Write source and test
            source_file = temp_path / file_name
            if file_name.endswith(".js"):
                test_file_name = file_name.replace(".js", ".test.js")
            else:
                test_file_name = f"{file_name}.test.js"
                source_file = temp_path / f"{file_name}.js"
                
            source_file.write_text(source_code, encoding="utf-8")
            test_file.write_text(test_code, encoding="utf-8")
            
            # 2. Install dependencies
            logger.info("Running npm install...")
            # Use shell=True on Windows for npm if needed, but subprocess with shell=False usually works 
            # if we use the right executable. On Windows it's npm.cmd
            npm_exe = "npm.cmd" if os.name == "nt" else "npm"
            npx_exe = "npx.cmd" if os.name == "nt" else "npx"
            
            subprocess.run(
                [npm_exe, "install", "--prefer-offline", "--no-audit", "--loglevel=error"],
                cwd=temp_dir,
                capture_output=True
            )
            
            # 3. Run Jest with coverage
            logger.info("Running jest...")
            jest_cmd = [
                npx_exe, "jest", 
                "--coverage", 
                "--coverageReporters=json-summary"
            ]
            
            process = subprocess.run(
                jest_cmd,
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
                
            # 4. Extract coverage
            coverage_val = None
            cov_json_path = temp_path / "coverage" / "coverage-summary.json"
            if cov_json_path.exists():
                try:
                    cov_data = json.loads(cov_json_path.read_text(encoding="utf-8"))
                    # Coverage summary format: {"total": {"lines": {"pct": 80.5}, ...}}
                    # We will take statement or line coverage.
                    total_cov = cov_data.get("total", {})
                    lines_cov = total_cov.get("lines", {}).get("pct", 0.0)
                    coverage_val = float(lines_cov)
                except Exception as e:
                    logger.warning(f"Failed to parse jest coverage-summary.json: {e}")
                    
            # 5. Run Stryker for Mutation Testing
            logger.info("Running stryker...")
            stryker_process = subprocess.run(
                [npx_exe, "stryker", "run"],
                cwd=temp_dir,
                capture_output=True,
                text=True
            )
            
            mut_stdout = stryker_process.stdout
            mutation_score = self._extract_mutation_score(mut_stdout)
            
            return SandboxResult(
                success=True,
                stdout=stdout + "\n" + mut_stdout,
                stderr=stderr + "\n" + stryker_process.stderr,
                error_log="",
                coverage=coverage_val,
                mutation_score=mutation_score
            )
            
    def _extract_mutation_score(self, stryker_output: str) -> Optional[float]:
        """Parse Stryker output for mutation score."""
        # Output: "Mutation score: 85.71%"
        match = re.search(r"Mutation score:\s*([0-9.]+)\s*%", stryker_output, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
        return None
