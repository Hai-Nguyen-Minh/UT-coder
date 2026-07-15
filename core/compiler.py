"""
core/compiler.py
----------------
AI-powered UT file compilation checker.

Uses the local LLM (via Ollama) to analyse a generated unit test file for
syntactic correctness, code quality, and potential compile/runtime issues.

The LLM acts as a "virtual compiler" — it reviews the test code and returns:
  - Whether the code looks syntactically correct
  - A list of potential issues (missing imports, wrong assertions, syntax errors, etc.)
  - Suggestions to fix each issue

This is especially useful for languages where the real compiler is not
available in the current environment (Java, C#, TS without toolchain).
"""

from __future__ import annotations

import logging
from typing import Generator

from core.code_parser import detect_language
from core.config import get_config
from core.llm import get_llm

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Language-specific review instructions
# ---------------------------------------------------------------------------

_LANG_CHECKLIST: dict[str, str] = {
    "python": (
        "- Check for valid Python syntax (indentation, colons, matching brackets).\n"
        "- Ensure all imported modules exist and are correct.\n"
        "- Verify that `test_` prefix is used on all test functions.\n"
        "- Check that assertions use `assert` or methods from `unittest.TestCase`.\n"
        "- Look for undefined variables, functions, or classes.\n"
        "- Ensure mock/patch targets match the actual import paths.\n"
    ),
    "java": (
        "- Check for valid Java syntax (braces, semicolons, type declarations).\n"
        "- Ensure all imports resolve to known packages (JUnit, Mockito, or standard lib).\n"
        "- Verify `@Test`, `@BeforeEach`, etc. annotations are correctly applied.\n"
        "- Check that class names match the file name.\n"
        "- Ensure method signatures match their usage (correct types, throws clauses).\n"
        "- Look for missing generics, unclosed strings, or misplaced brackets.\n"
    ),
    "csharp": (
        "- Check for valid C# syntax (braces, semicolons, using directives).\n"
        "- Ensure all `using` statements reference existing namespaces.\n"
        "- Verify `[Fact]`, `[Theory]`, `[InlineData]` attributes are used correctly.\n"
        "- Check that test methods are in a proper test class.\n"
        "- Look for missing type annotations, unclosed strings, or mismatched braces.\n"
    ),
    "javascript": (
        "- Check for valid JavaScript/TypeScript syntax.\n"
        "- Ensure `require` / `import` paths reference valid modules.\n"
        "- Verify `describe`, `it`, `test`, `expect` are from Jest.\n"
        "- Check for missing parentheses, brackets, or semicolons.\n"
        "- Look for undefined variables or misused async/await.\n"
    ),
    "typescript": (
        "- Check for valid TypeScript syntax (types, interfaces, generics).\n"
        "- Ensure all type annotations are correct and consistent.\n"
        "- Verify `describe`, `it`, `test`, `expect` are from Jest.\n"
        "- Check import paths resolve to actual modules.\n"
        "- Look for type mismatches, missing return types, or incorrect generics.\n"
    ),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compile_check(
    source_code: str,
    test_code: str,
    file_name: str,
    *,
    stream: bool = False,
) -> dict | Generator[str, None, None]:
    """
    AI-based compilation check for a unit test file.

    Uses the LLM to review the test code and identify potential compilation
    errors, syntax issues, and common mistakes.

    Args:
        source_code: The original source file content (for context).
        test_code:   The generated unit test code to check.
        file_name:   Original filename (used for language detection).
        stream:      If True, yields tokens progressively instead of returning
                     a final dict.

    Returns:
        If stream=False: a dict with keys:
            - "has_issues" (bool)
            - "issues" (list of dicts with "description", "line_reference", "suggestion")
            - "overall_assessment" (str)
        If stream=True: a generator yielding incremental string tokens.
    """
    logger.info("Running AI compile check for '%s'", file_name)

    language = detect_language(file_name)
    cfg = get_config()
    lang_cfg = cfg.get("languages", {}).get(language, {})
    framework = lang_cfg.get("test_framework", "an appropriate test framework")
    checklist = _LANG_CHECKLIST.get(language, _LANG_CHECKLIST.get("python", ""))

    system_prompt = (
        f"You are an expert {language} compiler and code reviewer.\n"
        f"Your task is to check a {framework} unit test file for compilation errors, "
        f"syntax mistakes, and common coding issues.\n\n"
        f"Review checklist:\n"
        f"{checklist}\n\n"
        f"Respond in this exact JSON format (no markdown fences, no extra text):\n"
        f"{{\n"
        f'  "has_issues": true or false,\n'
        f'  "issues": [\n'
        f'    {{\n'
        f'      "description": "Describe the issue clearly",\n'
        f'      "line_reference": "Line number or code snippet reference",\n'
        f'      "suggestion": "How to fix it"\n'
        f'    }}\n'
        f"  ],\n"
        f'  "overall_assessment": "Brief summary of code quality and correctness"\n'
        f"}}\n\n"
        f"IMPORTANT:\n"
        f"- Only flag ACTUAL issues — do not report false positives.\n"
        f"- If the code is correct and compilable, set `has_issues` to false and return an empty `issues` list.\n"
        f"- Output ONLY valid JSON — no surrounding text, no markdown fences."
    )

    user_prompt = (
        f"Review this {language} unit test file for compilation correctness.\n\n"
        f"Source file: `{file_name}`\n"
        f"Test framework: {framework}\n\n"
        f"--- Source Code ---\n"
        f"```{language}\n{source_code}\n```\n\n"
        f"--- Generated Test Code ---\n"
        f"```{language}\n{test_code}\n```\n\n"
        f"Check for syntax errors, missing imports, incorrect API usage, "
        f"and any code that would prevent compilation or execution."
    )

    # ------------------------------------------------------------------
    # Try Sandbox execution first
    # ------------------------------------------------------------------
    from core.sandbox import get_sandbox
    sandbox = get_sandbox(language)
    if sandbox.__class__.__name__ != "Sandbox":
        # We have a real sandbox for this language
        logger.info(f"Using actual Sandbox for compile check ({language})")
        result = sandbox.run_test(file_name, source_code, test_code)
        
        if stream:
            def _sandbox_stream(res):
                if res.success:
                    yield "✅ **Sandbox execution passed!**\nThe code compiled and the tests ran successfully without errors."
                else:
                    yield f"⚠️ **Sandbox execution failed.**\n\n```\n{res.error_log}\n```"
            return _sandbox_stream(result)
        else:
            issues = []
            if not result.success:
                # Truncate error log if it's too long
                err = result.error_log
                if len(err) > 1000:
                    err = err[-1000:]
                issues.append({
                    "description": err,
                    "line_reference": "N/A",
                    "suggestion": "Review the compiler/test runner output above."
                })
            return {
                "has_issues": not result.success,
                "issues": issues,
                "overall_assessment": "Sandbox execution passed." if result.success else "Sandbox execution failed."
            }

    # ------------------------------------------------------------------
    # Fallback to AI compilation check
    # ------------------------------------------------------------------
    logger.info("Sandbox not available, falling back to AI check")
    llm = get_llm()

    if stream:
        return _stream_check(llm, system_prompt, user_prompt)
    else:
        return _full_check(llm, system_prompt, user_prompt)


def _full_check(llm, system_prompt: str, user_prompt: str) -> dict:
    """Run a non-streaming compile check and parse the result."""
    import json
    import re

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
        # Ensure required keys exist
        result.setdefault("has_issues", False)
        result.setdefault("issues", [])
        result.setdefault("overall_assessment", "No assessment provided.")
        return result
    except json.JSONDecodeError:
        logger.warning(
            "Failed to parse LLM compile check output as JSON. Retrying with stricter prompt..."
        )
        # Retry with minimal JSON-only prompt
        try:
            retry_prompt = (
                f"Output ONLY valid JSON (no other text) for compile check.\n"
                f"Format: {{\"has_issues\": false, \"issues\": [], "
                f"\"overall_assessment\": \"Code looks correct.\"}}"
            )
            retry_response = llm.invoke([
                {"role": "system", "content": "You only output valid JSON. Never include extra text or code."},
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
            result.setdefault("has_issues", False)
            result.setdefault("issues", [])
            result.setdefault("overall_assessment", "")
            return result
        except Exception:
            pass

        return {
            "has_issues": True,
            "issues": [{"description": raw[:300] + "...", "line_reference": "", "suggestion": ""}],
            "overall_assessment": "Could not parse structured output. See raw response.",
        }


def _stream_check(llm, system_prompt: str, user_prompt: str) -> Generator[str, None, None]:
    """Stream the compile check response token by token."""
    for chunk in llm.stream([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]):
        content = chunk.content
        yield "".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in content) if isinstance(content, list) else str(content)


def quick_assessment(test_code: str, file_name: str) -> str:
    """
    Quick one-line assessment of test code quality.

    Returns a short string like "Looks good", "Has minor issues", or
    "Likely won't compile".
    """
    language = detect_language(file_name)

    system_prompt = (
        f"You are a {language} compiler expert. "
        f"Rate this unit test code with exactly ONE word: "
        f"GOOD, MINOR_ISSUES, or BROKEN. "
        f"Output ONLY that single word, nothing else."
    )

    user_prompt = (
        f"Test code:\n```{language}\n{test_code}\n```\n"
        f"Your single-word assessment:"
    )

    llm = get_llm()
    response = llm.invoke([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ])

    raw_content = response.content
    raw = "".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in raw_content) if isinstance(raw_content, list) else str(raw_content)
    return raw.strip()
