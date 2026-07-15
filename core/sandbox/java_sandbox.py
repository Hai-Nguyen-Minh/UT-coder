import logging
import os
import re
import subprocess
import tempfile
import csv
from pathlib import Path
from typing import Optional

from .base import Sandbox, SandboxResult

logger = logging.getLogger(__name__)

POM_TEMPLATE = """<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>
    <groupId>utcoder</groupId>
    <artifactId>sandbox</artifactId>
    <version>1.0-SNAPSHOT</version>

    <properties>
        <maven.compiler.source>21</maven.compiler.source>
        <maven.compiler.target>21</maven.compiler.target>
        <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
    </properties>

    <dependencies>
        <dependency>
            <groupId>org.junit.jupiter</groupId>
            <artifactId>junit-jupiter-api</artifactId>
            <version>5.10.0</version>
            <scope>test</scope>
        </dependency>
        <dependency>
            <groupId>org.junit.jupiter</groupId>
            <artifactId>junit-jupiter-engine</artifactId>
            <version>5.10.0</version>
            <scope>test</scope>
        </dependency>
        <dependency>
            <groupId>org.mockito</groupId>
            <artifactId>mockito-core</artifactId>
            <version>5.5.0</version>
            <scope>test</scope>
        </dependency>
    </dependencies>

    <build>
        <plugins>
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-surefire-plugin</artifactId>
                <version>3.1.2</version>
            </plugin>
            <plugin>
                <groupId>org.jacoco</groupId>
                <artifactId>jacoco-maven-plugin</artifactId>
                <version>0.8.10</version>
                <executions>
                    <execution>
                        <goals>
                            <goal>prepare-agent</goal>
                        </goals>
                    </execution>
                    <execution>
                        <id>report</id>
                        <phase>test</phase>
                        <goals>
                            <goal>report</goal>
                        </goals>
                    </execution>
                </executions>
            </plugin>
            <plugin>
                <groupId>org.pitest</groupId>
                <artifactId>pitest-maven</artifactId>
                <version>1.15.0</version>
                <dependencies>
                    <dependency>
                        <groupId>org.pitest</groupId>
                        <artifactId>pitest-junit5-plugin</artifactId>
                        <version>1.2.0</version>
                    </dependency>
                </dependencies>
            </plugin>
        </plugins>
    </build>
</project>
"""

class JavaSandbox(Sandbox):
    """Execution sandbox for Java using Maven, JaCoCo, and PIT."""

    def run_test(self, file_name: str, source_code: str, test_code: str) -> SandboxResult:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # 1. Setup directory structure
            main_java = temp_path / "src" / "main" / "java"
            test_java = temp_path / "src" / "test" / "java"
            main_java.mkdir(parents=True, exist_ok=True)
            test_java.mkdir(parents=True, exist_ok=True)
            
            # Write pom.xml
            pom_file = temp_path / "pom.xml"
            pom_file.write_text(POM_TEMPLATE, encoding="utf-8")
            
            # 2. Write source and test files
            # For Java, class name must match file name.
            source_file = main_java / file_name
            
            # Determine test file name (usually ClassNameTest.java)
            if file_name.endswith(".java"):
                test_file_name = file_name.replace(".java", "Test.java")
            else:
                test_file_name = f"{file_name}Test"
                
            test_file = test_java / test_file_name
            
            source_file.write_text(source_code, encoding="utf-8")
            test_file.write_text(test_code, encoding="utf-8")
            
            # 3. Run tests with JaCoCo
            # We run Maven in batch mode to avoid terminal control chars
            logger.info("Running maven test...")
            process = subprocess.run(
                ["mvn", "-B", "clean", "test"],
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
                
            # 4. Extract coverage from JaCoCo CSV
            coverage_val = None
            jacoco_csv = temp_path / "target" / "site" / "jacoco" / "jacoco.csv"
            if jacoco_csv.exists():
                try:
                    with open(jacoco_csv, "r", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        total_missed = 0
                        total_covered = 0
                        for row in reader:
                            total_missed += int(row.get("LINE_MISSED", 0))
                            total_covered += int(row.get("LINE_COVERED", 0))
                        
                        total_lines = total_missed + total_covered
                        if total_lines > 0:
                            coverage_val = (total_covered / total_lines) * 100.0
                        else:
                            coverage_val = 0.0
                except Exception as e:
                    logger.warning(f"Failed to parse JaCoCo CSV: {e}")
                    
            # 5. Run PIT for Mutation Testing
            logger.info("Running maven pitest...")
            pit_process = subprocess.run(
                ["mvn", "-B", "pitest:mutationCoverage"],
                cwd=temp_dir,
                capture_output=True,
                text=True
            )
            
            mut_stdout = pit_process.stdout
            mutation_score = self._extract_mutation_score(mut_stdout)
            
            return SandboxResult(
                success=True,
                stdout=stdout + "\n" + mut_stdout,
                stderr=stderr + "\n" + pit_process.stderr,
                error_log="",
                coverage=coverage_val,
                mutation_score=mutation_score
            )
            
    def _extract_mutation_score(self, pit_output: str) -> Optional[float]:
        """Parse PIT output to calculate mutation score."""
        # PIT output: ">> Generated 10 mutations Killed 8 (80%)"
        match = re.search(r"Generated\s+\d+\s+mutations\s+Killed\s+\d+\s+\((\d+)%\)", pit_output)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
        return None
