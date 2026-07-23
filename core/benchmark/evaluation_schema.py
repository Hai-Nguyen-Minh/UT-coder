"""Versioned result schema and scoring rules for the benchmark evaluator."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


SCHEMA_VERSION = "2.0"
EVALUATOR_VERSION = "2.0.0"


class EvaluationStatus(str, Enum):
    """Stable machine-readable outcomes for one generated test suite."""

    VALID_STABLE = "VALID_STABLE"
    VALID_FLAKY = "VALID_FLAKY"
    NO_GENERATED_TEST = "NO_GENERATED_TEST"
    SOURCE_COMPILE_FAILED = "SOURCE_COMPILE_FAILED"
    TEST_COMPILE_FAILED = "TEST_COMPILE_FAILED"
    COMPILE_TIMEOUT = "COMPILE_TIMEOUT"
    COLLECTION_FAILED = "COLLECTION_FAILED"
    NO_TESTS = "NO_TESTS"
    ALL_SKIPPED = "ALL_SKIPPED"
    UNSTABLE = "UNSTABLE"
    COVERAGE_FAILED = "COVERAGE_FAILED"
    MUTATION_INCOMPLETE = "MUTATION_INCOMPLETE"
    INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"


@dataclass
class TestRunSummary:
    """Counts from one isolated pytest process."""

    exit_code: int | None = None
    collected: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    xfailed: int = 0
    xpassed: int = 0
    duration_seconds: float = 0.0
    timed_out: bool = False
    report_valid: bool = False

    @property
    def successful(self) -> bool:
        return bool(
            self.report_valid
            and self.exit_code == 0
            and self.collected > 0
            and self.passed > 0
            and self.failed == 0
            and self.errors == 0
        )

    @property
    def all_skipped(self) -> bool:
        return bool(
            self.report_valid
            and self.collected > 0
            and self.passed == 0
            and self.failed == 0
            and self.errors == 0
            and self.skipped + self.xfailed >= self.collected
        )


@dataclass
class CoverageSummary:
    """Coverage.py statement and branch metrics for the source module."""

    line_percent: float | None = None
    branch_percent: float | None = None
    covered_lines: int = 0
    num_statements: int = 0
    covered_branches: int = 0
    num_branches: int = 0
    valid: bool = False


@dataclass
class MutationSummary:
    """Normalized mutmut outcomes.

    Mutants that are not reached by any test are deliberately counted as
    undetected. Excluding them would reward a suite for never exercising the
    mutated function. Tool-level suspicious/skipped/interrupted mutants are
    excluded and exposed separately.
    """

    killed: int = 0
    timed_out: int = 0
    segfault: int = 0
    survived: int = 0
    no_tests: int = 0
    suspicious: int = 0
    skipped: int = 0
    interrupted: int = 0
    total: int = 0
    completed: int = 0
    duration_seconds: float = 0.0
    complete: bool = False
    reason: str = ""

    @property
    def detected(self) -> int:
        return self.killed + self.timed_out + self.segfault

    @property
    def undetected(self) -> int:
        return self.survived + self.no_tests

    @property
    def applicable(self) -> int:
        return self.detected + self.undetected

    @property
    def excluded(self) -> int:
        return self.suspicious + self.skipped + self.interrupted

    @property
    def score_percent(self) -> float | None:
        if not self.complete or self.applicable <= 0:
            return None
        return 100.0 * self.detected / self.applicable


def _clamp_percent(value: float | None) -> float:
    if value is None:
        return 0.0
    return min(100.0, max(0.0, float(value)))


def calculate_quality_score(
    *,
    line_percent: float,
    branch_percent: float,
    mutation_percent: float | None,
    stability_passed_runs: int,
) -> tuple[float, float, float, bool]:
    """Return base, multiplier, final, and whether weights were normalized.

    A source with no applicable mutants does not receive 55 free points. Its
    coverage weights are normalized from 30:15 to 2:1 and the result records
    that mutation was not applicable.
    """

    line = _clamp_percent(line_percent) / 100.0
    branch = _clamp_percent(branch_percent) / 100.0
    if stability_passed_runs >= 3:
        multiplier = 1.0
    elif stability_passed_runs == 2:
        multiplier = 0.8
    else:
        return 0.0, 0.0, 0.0, False

    normalized = mutation_percent is None
    if normalized:
        base = 100.0 * ((2.0 / 3.0) * branch + (1.0 / 3.0) * line)
    else:
        mutation = _clamp_percent(mutation_percent) / 100.0
        base = 100.0 * (0.55 * mutation + 0.30 * branch + 0.15 * line)
    base = round(base, 4)
    return base, multiplier, round(base * multiplier, 4), normalized


def quality_band(score: float | None, *, valid: bool) -> str:
    if not valid or score is None:
        return "INVALID"
    if score >= 85.0:
        return "EXCELLENT"
    if score >= 70.0:
        return "GOOD"
    if score >= 50.0:
        return "FAIR"
    return "WEAK"


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass
class EvaluationResult:
    """Complete, serializable quality evaluation for one generated suite."""

    status: str
    source_hash: str
    test_hash: str
    valid: bool = False
    score_complete: bool = False
    stable: bool = False
    stability_passed_runs: int = 0
    stability_multiplier: float = 0.0
    collection: TestRunSummary = field(default_factory=TestRunSummary)
    stability_runs: list[TestRunSummary] = field(default_factory=list)
    coverage_run: TestRunSummary = field(default_factory=TestRunSummary)
    coverage: CoverageSummary = field(default_factory=CoverageSummary)
    mutation: MutationSummary = field(default_factory=MutationSummary)
    base_score: float | None = None
    final_score: float | None = None
    mutation_weights_normalized: bool = False
    band: str = "INVALID"
    duration_seconds: float = 0.0
    diagnostics: list[str] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION
    evaluator_version: str = EVALUATOR_VERSION

    def finalize_score(self) -> None:
        mutation_score = self.mutation.score_percent
        base, multiplier, final, normalized = calculate_quality_score(
            line_percent=float(self.coverage.line_percent or 0.0),
            branch_percent=float(self.coverage.branch_percent or 0.0),
            mutation_percent=mutation_score,
            stability_passed_runs=self.stability_passed_runs,
        )
        self.base_score = base
        self.stability_multiplier = multiplier
        self.final_score = final
        self.mutation_weights_normalized = normalized
        self.score_complete = True
        self.band = quality_band(final, valid=self.valid)

    def finalize_invalid_score(self) -> None:
        """Hard-gate failures are completed evaluations with an explicit zero."""

        self.valid = False
        self.score_complete = True
        self.stable = False
        self.stability_multiplier = 0.0
        self.base_score = 0.0
        self.final_score = 0.0
        self.mutation_weights_normalized = False
        self.band = "INVALID"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def empty(
        cls,
        status: EvaluationStatus | str,
        *,
        source_code: str,
        test_code: str = "",
        diagnostic: str = "",
    ) -> "EvaluationResult":
        result = cls(
            status=status.value if isinstance(status, EvaluationStatus) else str(status),
            source_hash=content_hash(source_code),
            test_hash=content_hash(test_code),
        )
        if diagnostic:
            result.diagnostics.append(diagnostic)
        return result
