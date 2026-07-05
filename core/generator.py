"""
core/generator.py
-----------------
Orchestrates the full unit-test generation pipeline:
  1. Parse source code into chunks via code_parser
  2. Embed and index chunks into ChromaDB via vectorstore
  3. Retrieve contextually similar snippets (RAG)
  4. Build a structured prompt using the framework from config.json
  5. Stream the LLM response token-by-token
"""

from __future__ import annotations

import logging
import re
from typing import Generator

from core.code_parser import detect_language, parse_code
from core.config import get_config
from core.llm import get_llm
from core import vectorstore as vs

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt templates per language — injected into system prompt
# ---------------------------------------------------------------------------

_LANG_INSTRUCTIONS: dict[str, str] = {
    "python": (
        "- Import the module under test at the top of the test file.\n"
        "- Use `pytest` fixtures and parametrize where it adds value.\n"
        "- Prefix all test functions with `test_`.\n"
        "- Use `unittest.mock.patch` or `pytest-mock` for mocking.\n"
        "- Include a `conftest.py` section comment if shared fixtures are needed.\n"
    ),
    "java": (
        "- Import `org.junit.jupiter.api.*` and `org.mockito.Mockito.*`.\n"
        "- Annotate test methods with `@Test`.\n"
        "- Use `@BeforeEach` / `@AfterEach` for setup/teardown.\n"
        "- Use `Assertions.assertEquals`, `assertThrows`, etc.\n"
        "- Mock dependencies with `@Mock` and `@InjectMocks`.\n"
    ),
    "csharp": (
        "- Use `xUnit` with `[Fact]` and `[Theory]` attributes.\n"
        "- Use `Moq` for mocking interfaces and dependencies.\n"
        "- Follow the Arrange-Act-Assert pattern in every test.\n"
        "- Use `Assert.Equal`, `Assert.Throws<T>`, etc.\n"
        "- Group tests in a class matching `<ClassName>Tests`.\n"
    ),
    "javascript": (
        "- Use `Jest` with `describe` / `it` or `test` blocks.\n"
        "- Use `jest.fn()` and `jest.spyOn()` for mocking.\n"
        "- Use `expect(...).toBe(...)`, `toEqual`, `toThrow`, etc.\n"
        "- Include `beforeEach` / `afterEach` where appropriate.\n"
        "- Mock ES modules with `jest.mock('...')`.\n"
    ),
}


def _sanitize_collection_name(file_name: str) -> str:
    """Convert a filename to a valid ChromaDB collection name (max 63 chars)."""
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", file_name)
    name = re.sub(r"_+", "_", name).strip("_")
    return f"utcoder_{name}"[:63]


def index_code(file_name: str, source_code: str) -> str:
    """
    Parse and embed a source file into ChromaDB.

    Returns:
        The ChromaDB collection name used.
    """
    docs = parse_code(file_name, source_code)
    col_name = _sanitize_collection_name(file_name)
    logger.info("Indexing '%s' → collection '%s' (%d chunks)", file_name, col_name, len(docs))
    vs.index_documents(docs, col_name)
    return col_name


def generate_unit_tests(
    file_name: str,
    source_code: str,
) -> Generator[str, None, None]:
    """
    Full pipeline: index → retrieve context → stream unit tests.

    Args:
        file_name:   Original filename (used for language detection & naming).
        source_code: Raw source code content.

    Yields:
        Incremental string tokens from the LLM.
    """
    cfg = get_config()
    language = detect_language(file_name)

    # ------------------------------------------------------------------
    # Pull test framework from config.json languages section
    # ------------------------------------------------------------------
    lang_cfg = cfg.get("languages", {}).get(language, {})
    framework = lang_cfg.get("test_framework", "an appropriate test framework")
    lang_instructions = _LANG_INSTRUCTIONS.get(language, "")

    # ------------------------------------------------------------------
    # Index code and retrieve relevant context via RAG
    # ------------------------------------------------------------------
    col_name = index_code(file_name, source_code)

    context_snippets = vs.similarity_search(
        query=f"functions methods classes interfaces in {file_name}",
        collection_name=col_name,
        k=4,
    )
    context_block = ""
    if context_snippets:
        joined = "\n\n---\n\n".join(d.page_content for d in context_snippets)
        context_block = f"\n\nRelevant context retrieved from ChromaDB:\n```\n{joined}\n```"

    # ------------------------------------------------------------------
    # Build prompts
    # ------------------------------------------------------------------
    system_prompt = (
        f"You are a senior software engineer and testing expert specialising in {language}.\n"
        f"Your task is to generate a COMPLETE, production-quality unit test file "
        f"for the source code provided by the user.\n\n"
        f"Test framework: **{framework}**\n\n"
        f"Requirements:\n"
        f"{lang_instructions}"
        f"- Cover ALL public functions, methods, and classes.\n"
        f"- Include happy-path, edge case, boundary, and error/exception tests.\n"
        f"- Write descriptive test names that read like sentences.\n"
        f"- Add inline comments for non-obvious test logic.\n"
        f"- Output ONLY the test file source code — no markdown fences, no prose, "
        f"no explanation before or after the code.\n"
        f"- The output must be valid, executable {language} code."
    )

    user_prompt = (
        f"Generate comprehensive {framework} unit tests for this {language} file: `{file_name}`\n\n"
        f"Source Code:\n```{language}\n{source_code}\n```"
        f"{context_block}"
    )

    # ------------------------------------------------------------------
    # Stream LLM response
    # ------------------------------------------------------------------
    llm = get_llm()
    logger.info(
        "Streaming unit tests for '%s' (language=%s, framework=%s)",
        file_name, language, framework,
    )

    for chunk in llm.stream(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ]
    ):
        yield chunk.content
