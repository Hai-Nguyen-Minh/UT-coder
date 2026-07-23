"""
core/coverager.py
-----------------
AI-powered UT file coverage analyser.

Uses the local LLM (via Ollama) to estimate code coverage that a generated
unit test file would achieve, WITHOUT actually running the tests.

The LLM analyses the source code and the generated test code, then returns:
  - Which lines/functions are covered by the tests
  - Which lines/functions are NOT covered
  - An estimated coverage percentage
  - Suggestions to improve coverage

This is a "virtual coverage" tool — it helps developers quickly assess test
completeness before they have the full compilation/testing pipeline available.
"""

from __future__ import annotations

import logging
import re
from typing import Generator

from core.code_parser import detect_language
from core.config import get_config
from core.llm import get_llm

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Language-specific coverage criteria
# ---------------------------------------------------------------------------

_COVERAGE_CRITERIA: dict[str, str] = {
    "python": (
        "- Every public function/method in the source should be called at least once.\n"
        "- Each branch (if/else, try/except) should have a test case.\n"
        "- Edge cases (empty input, None, boundary values) should be tested.\n"
        "- Error/exception paths should be verified.\n"
    ),
    "java": (
        "- Every public method should be invoked in at least one test.\n"
        "- Conditional branches (if/else, switch) should be exercised.\n"
        "- Exception paths should be tested with `assertThrows`.\n"
        "- Edge cases (null inputs, max values, empty collections) should be covered.\n"
    ),
    "csharp": (
        "- All public methods should have corresponding [Fact] or [Theory] tests.\n"
        "- Branch coverage: if/else, switch, try/catch should be tested.\n"
        "- Exception paths verified with Assert.Throws<T>.\n"
        "- Edge cases like null, empty strings, boundary values covered.\n"
    ),
    "javascript": (
        "- All exported functions should be tested.\n"
        "- Branch paths (if/else, ternary, try/catch) exercised.\n"
        "- Async error handling (rejected promises) tested.\n"
        "- Edge cases: undefined, null, empty arrays/objects covered.\n"
    ),
    "typescript": (
        "- All exported functions/methods should have tests.\n"
        "- Branch paths exercised.\n"
        "- Type edge cases (null, undefined, union type boundaries) covered.\n"
        "- Async error handling tested.\n"
    ),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyse_coverage(
    source_code: str,
    test_code: str,
    file_name: str,
    *,
    stream: bool = False,
) -> dict | Generator[str, None, None]:
    """
    AI-based coverage analysis for a unit test file.

    Uses the LLM to estimate which parts of the source code are covered
    by the generated tests, without actually compiling or running anything.

    Args:
        source_code: The original source file content.
        test_code:   The generated unit test code.
        file_name:   Original filename (for language detection).
        stream:      If True, yields tokens progressively.

    Returns:
        If stream=False: a dict with keys:
            - "coverage_pct" (float) — estimated coverage percentage
            - "covered_items" (list of str) — functions/lines that are covered
            - "uncovered_items" (list of str) — functions/lines NOT covered
            - "covered_lines" (list of int) — estimated covered line numbers
            - "uncovered_lines" (list of int) — estimated uncovered line numbers
            - "suggestions" (list of str) — ideas to improve coverage
        If stream=True: a generator yielding incremental string tokens.
    """
    logger.info("Running AI coverage analysis for '%s'", file_name)

    language = detect_language(file_name)
    cfg = get_config()
    lang_cfg = cfg.get("languages", {}).get(language, {})
    framework = lang_cfg.get("test_framework", "an appropriate test framework")
    criteria = _COVERAGE_CRITERIA.get(language, _COVERAGE_CRITERIA.get("python", ""))

    source_lines = source_code.split("\n")
    source_line_count = len(source_lines)

    system_prompt = (
        f"You are an expert {language} code coverage analyst.\n"
        f"Your task is to estimate code coverage for a {framework} unit test file "
        f"by carefully analysing which parts of the source code are exercised.\n\n"
        f"Coverage criteria:\n"
        f"{criteria}\n\n"
        f"Respond in this exact JSON format (no markdown fences, no extra text):\n"
        f"{{\n"
        f'  "coverage_pct": <float between 0 and 100>,\n'
        f'  "covered_items": ["list of covered functions, methods, or code sections"],\n'
        f'  "uncovered_items": ["list of functions/methods NOT covered"],\n'
        f'  "covered_lines": [<list of 1-based line numbers that are covered>],\n'
        f'  "uncovered_lines": [<list of 1-based line numbers NOT covered>],\n'
        f'  "suggestions": ["list of suggestions to improve coverage"]\n'
        f"}}\n\n"
        f"IMPORTANT:\n"
        f"- Analyse ACTUAL test invocations, not just imports.\n"
        f"- A line is 'covered' if the test exercises that specific line's logic.\n"
        f"- Be conservative — if unsure whether a line is tested, mark it uncovered.\n"
        f"- Output ONLY valid JSON — no surrounding text, no markdown fences."
    )

    user_prompt = (
        f"Analyse code coverage for this {language} file.\n\n"
        f"Source file: `{file_name}`\n"
        f"Source lines: {source_line_count}\n"
        f"Test framework: {framework}\n\n"
        f"--- Source Code (with line numbers) ---\n"
        f"```{language}\n{_add_line_numbers(source_code)}\n```\n\n"
        f"--- Generated Test Code ---\n"
        f"```{language}\n{test_code}\n```\n\n"
        f"For each line of the source code, determine if the test exercises it. "
        f"Return the estimated coverage percentage, the covered/uncovered line numbers, "
        f"and suggestions for improving coverage."
    )

    # ------------------------------------------------------------------
    # Try Sandbox execution first
    # ------------------------------------------------------------------
    from core.sandbox import get_sandbox
    sandbox = get_sandbox(language)
    if sandbox.__class__.__name__ != "Sandbox":
        logger.info(f"Using actual Sandbox for coverage check ({language})")
        result = sandbox.run_test(file_name, source_code, test_code)
        coverage_valid = bool(
            result.coverage_valid
            or (result.execution_status == "unknown" and result.coverage is not None)
        )
        
        if stream:
            def _sandbox_stream(res):
                if coverage_valid and res.coverage is not None and res.success:
                    yield f"📊 **Sandbox Coverage: {res.coverage:.1f}%**\n(Coverage measured directly from sandbox execution)"
                elif coverage_valid and res.coverage is not None:
                    yield f"Diagnostic Coverage: {res.coverage:.1f}% (pytest failed; not accepted)."
                else:
                    yield "⚠️ **Sandbox execution failed.** Cannot measure coverage."
            return _sandbox_stream(result)
        else:
            return {
                "coverage_pct": result.coverage if coverage_valid and result.coverage is not None else 0.0,
                "covered_items": [],
                "uncovered_items": [],
                "covered_lines": [],
                "uncovered_lines": [],
                "suggestions": [
                    (
                        "Coverage is valid and pytest passed."
                        if result.success and coverage_valid
                        else "Coverage is diagnostic only because pytest failed."
                        if coverage_valid
                        else f"Coverage is invalid; sandbox status: {result.execution_status}."
                    )
                ]
            }

    # ------------------------------------------------------------------
    # Fallback to AI coverage check
    # ------------------------------------------------------------------
    logger.info("Sandbox not available, falling back to AI coverage check")
    llm = get_llm()

    if stream:
        return _stream_coverage(llm, system_prompt, user_prompt)
    else:
        return _full_coverage(llm, system_prompt, user_prompt, source_line_count)


def _full_coverage(
    llm,
    system_prompt: str,
    user_prompt: str,
    source_line_count: int,
) -> dict:
    """Run a non-streaming coverage analysis and parse the result."""
    import json

    response = llm.invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ])

    raw_content = response.content
    raw = "".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in raw_content) if isinstance(raw_content, list) else str(raw_content)
    raw = raw.strip()

    # Robust JSON extraction: handle markdown fences first
    fence_match = re.search(r"```(?:json)?\s*\n([\s\S]*?)\n```", raw)
    if fence_match:
        raw = fence_match.group(1).strip()

    # Then try to extract JSON object from remaining text
    json_match = re.search(r"\{[\s\S]*\}", raw)
    if json_match:
        raw = json_match.group(0)

    # Clean up stray control characters that break JSON parsing
    raw = re.sub(r"[\x00-\x1f\x7f]", "", raw)

    try:
        result = json.loads(raw)
        # Ensure required keys exist with defaults
        result.setdefault("coverage_pct", 0.0)
        result.setdefault("covered_items", [])
        result.setdefault("uncovered_items", [])
        result.setdefault("covered_lines", [])
        result.setdefault("uncovered_lines", [])
        result.setdefault("suggestions", [])

        # Clamp coverage_pct
        result["coverage_pct"] = max(0.0, min(100.0, float(result["coverage_pct"])))

        # Filter line numbers to valid range
        result["covered_lines"] = [
            ln for ln in result.get("covered_lines", [])
            if isinstance(ln, int) and 1 <= ln <= source_line_count
        ]
        result["uncovered_lines"] = [
            ln for ln in result.get("uncovered_lines", [])
            if isinstance(ln, int) and 1 <= ln <= source_line_count
        ]

        return result

    except json.JSONDecodeError:
        logger.warning(
            "Failed to parse LLM coverage output as JSON. Retrying with stricter prompt..."
        )
        # Retry with an extremely minimal prompt asking ONLY for JSON
        try:
            retry_prompt = (
                f"Output ONLY valid JSON (no other text) for coverage analysis.\n"
                f"Format: {{\"coverage_pct\": 85.0, \"covered_items\": [...], "
                f"\"uncovered_items\": [...], \"covered_lines\": [...], "
                f"\"uncovered_lines\": [...], \"suggestions\": [...]}}"
            )
            retry_response = llm.invoke([
                {"role": "system", "content": "You only output valid JSON. Never include markdown fences, extra text, or code."},
                {"role": "user", "content": retry_prompt},
            ])
            retry_raw_content = retry_response.content
            retry_raw = "".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in retry_raw_content) if isinstance(retry_raw_content, list) else str(retry_raw_content)
            retry_raw = retry_raw.strip()
            fence_match = re.search(r"```(?:json)?\s*\n([\s\S]*?)\n```", retry_raw)
            if fence_match:
                retry_raw = fence_match.group(1).strip()
            json_match = re.search(r"\{[\s\S]*\}", retry_raw)
            if json_match:
                retry_raw = json_match.group(0)
            result = json.loads(retry_raw)
            result.setdefault("coverage_pct", 0.0)
            result.setdefault("covered_items", [])
            result.setdefault("uncovered_items", [])
            result.setdefault("covered_lines", [])
            result.setdefault("uncovered_lines", [])
            result.setdefault("suggestions", [])
            return result
        except Exception:
            pass

        return {
            "coverage_pct": 0.0,
            "covered_items": [],
            "uncovered_items": [],
            "covered_lines": [],
            "uncovered_lines": [],
            "suggestions": [f"Could not parse structured output. Raw: {raw[:200]}..."],
        }


def _stream_coverage(
    llm,
    system_prompt: str,
    user_prompt: str,
) -> Generator[str, None, None]:
    """Stream the coverage analysis response token by token."""
    for chunk in llm.stream([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]):
        content = chunk.content
        yield "".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in content) if isinstance(content, list) else str(content)


def coverage_summary(
    source_code: str,
    test_code: str,
    file_name: str,
) -> str:
    """
    Quick coverage summary — returns a human-readable short string.

    Example: "Coverage: ~72% (5 functions covered, 2 uncovered)"
    """
    result = analyse_coverage(source_code, test_code, file_name)

    if isinstance(result, dict):
        pct = result.get("coverage_pct", 0)
        covered = len(result.get("covered_items", []))
        uncovered = len(result.get("uncovered_items", []))
        if covered + uncovered > 0:
            return f"Coverage: ~{pct:.0f}% ({covered} covered, {uncovered} uncovered)"
        else:
            return f"Coverage: ~{pct:.0f}%"
    return "Coverage analysis in progress..."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add_line_numbers(code: str) -> str:
    """Add 1-based line numbers to each line of code for reference."""
    lines = code.split("\n")
    # Calculate padding width based on line count
    width = len(str(len(lines)))
    numbered = [f"{i+1:>{width}} | {line}" for i, line in enumerate(lines)]
    return "\n".join(numbered)
