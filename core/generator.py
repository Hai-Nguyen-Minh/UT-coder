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
from pathlib import Path
from typing import Generator

from core.code_parser import detect_language, parse_code
from core.config import get_config
from core.llm import get_llm
from core import vectorstore as vs

logger = logging.getLogger(__name__)

def dump_trace(title: str, content: str):
    """Utility to dump full LLM and Sandbox logs to a file for debugging."""
    try:
        with open("llm_trace.log", "a", encoding="utf-8") as f:
            import datetime
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"\n[{ts}] {'='*20} {title} {'='*20}\n")
            f.write(str(content) + "\n")
    except Exception as e:
        logger.error(f"Failed to write trace: {e}")

# ---------------------------------------------------------------------------
# Prompt templates per language — injected into system prompt
# ---------------------------------------------------------------------------

_LANG_INSTRUCTIONS: dict[str, str] = {
    "python": (
        "- MANDATORY: The first line of the test file MUST be `import pytest`.\n"
        "- MANDATORY: The second line MUST be `from module_under_test import ...` (import all public symbols).\n"
        "- NEVER use any other module name. ONLY import from `module_under_test`.\n"
        "- Use `pytest.raises(...)` for testing exceptions.\n"
        "- Use `pytest` fixtures and parametrize where it adds value.\n"
        "- Prefix all test functions with `test_`.\n"
        "- Use `unittest.mock.patch` or `pytest-mock` for mocking.\n"
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
        f"- Output ONLY the test file source code inside a markdown code block (```). "
        f"Do not include any prose or explanation before or after the code block.\n"
        f"- The output must be valid, executable {language} code."
    )

    user_prompt = (
        f"Generate comprehensive {framework} unit tests for this {language} file: `{file_name}`\n\n"
        f"CRITICAL INSTRUCTION: You must import the functions/classes to test from the module `module_under_test`. Do not invent module names.\n\n"
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
        content = chunk.content
        if isinstance(content, list):
            content = "".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in content)
        yield content.replace("module_under_test", Path(file_name).stem)


def generate_with_reflection(
    file_name: str,
    source_code: str,
    max_retries: int = 3,
    target_coverage: float = 80.0
) -> Generator[tuple[str, str, dict], None, None]:
    """
    Generate unit tests with an inner reflection loop.
    Generates code, runs it in the Sandbox. If it fails or coverage is below target, feeds the error back to the LLM.
    Returns: (status_message, generated_code, sandbox_result_dict)
    """
    from core.sandbox import get_sandbox
    import re

    language = detect_language(file_name)
    sandbox = get_sandbox(language)
    
    # 1. Initial generation (no stream)
    llm = get_llm()
    
    # Reuse prompts from stream method
    cfg = get_config().get("languages", {}).get(language, {})
    framework = cfg.get("test_framework", "Unknown")
    lang_instructions = _LANG_INSTRUCTIONS.get(language, "")

    # Retrieve context from ChromaDB (source chunks)
    context_block = ""
    try:
        docs = vs.similarity_search(query=source_code, collection_name=_sanitize_collection_name(file_name), k=3)
        if docs:
            context_joined = "\n\n".join(d.page_content for d in docs)
            context_block = f"\n\nContext from other files:\n{context_joined}"
    except Exception:
        pass  # Collection may not exist if indexing was skipped

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
        f"- Output ONLY the test file source code inside a markdown code block (```). "
        f"Do not include any prose or explanation before or after the code block.\n"
        f"- The output must be valid, executable {language} code."
    )

    # Retrieve few-shot examples (source→test pairs) from the seed collection
    fewshot_block = ""
    try:
        filter_dict = {"language": language} if language != "python" else None
        fewshot_snippets = vs.similarity_search(
            query=source_code[:500],
            collection_name="utcoder_fewshot_examples",
            k=2,
            filter=filter_dict
        )
        if fewshot_snippets:
            fewshot_joined = "\n\n".join(d.page_content for d in fewshot_snippets)
            fewshot_block = (
                f"\n\nHere are reference examples of correct source→test pairs. "
                f"Follow the same style, import pattern (`from module_under_test import ...`), "
                f"and testing patterns:\n\n{fewshot_joined}"
            )
    except Exception:
        pass  # Collection may not exist yet

    user_prompt = (
        f"Generate comprehensive {framework} unit tests for this {language} file: `{file_name}`\n\n"
        f"CRITICAL RULES (VIOLATION = INSTANT FAILURE):\n"
        f"1. The test file MUST start with `import pytest` on the very first line.\n"
        f"2. Import ALL functions/classes from `module_under_test` ONLY. Example: `from module_under_test import func1, func2, MyClass`\n"
        f"3. NEVER use the original filename `{Path(file_name).stem}` as module name. ALWAYS use `module_under_test`.\n"
        f"4. Use `pytest.raises(ExceptionType)` for exception tests (NOT try/except).\n\n"
        f"Source Code:\n```{language}\n{source_code}\n```"
        f"{fewshot_block}"
        f"{context_block}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt},
    ]

    logger.info(f"Starting Reflection Loop for {file_name} (max_retries={max_retries}, target_cov={target_coverage}%)")
    dump_trace(f"REFLECTION LOOP START: {file_name}", f"System Prompt:\n{system_prompt}\n\nUser Prompt:\n{user_prompt}")
    
    best_code = ""
    best_result = None
    
    for attempt in range(max_retries + 1):
        status = f"🔄 Self-Reflection Attempt {attempt + 1}/{max_retries + 1}: Generating code..."
        logger.info(status)
        
        generated_code = ""
        for chunk in llm.stream(messages):
            content = chunk.content
            if isinstance(content, list):
                content = "".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in content)
            generated_code += content
            # Yield to UI with the real file name
            yield (status, generated_code.replace("module_under_test", Path(file_name).stem), {})
        
        # Clean the code from markdown fences
        blocks = re.findall(r"```(?:[a-zA-Z0-9+#]+)?\s*\n(.*?)\n```", generated_code, re.DOTALL)
        if blocks:
            clean_code = max(blocks, key=len)
        else:
            match = re.search(r"```(?:[a-zA-Z0-9+#]+)?\s*\n(.*)", generated_code, re.DOTALL)
            if match:
                clean_code = match.group(1)
            else:
                clean_code = generated_code

        # Safety: If it generated pure prose with no basic code structures, skip sandbox
        if language == "python" and not any(kw in clean_code for kw in ["import ", "def ", "class ", "assert "]):
            msg = "⚠️ AI output was pure text. Forcing retry..."
            logger.warning(msg)
            yield (msg, best_code.replace("module_under_test", Path(file_name).stem), {})
            
            if attempt < max_retries:
                messages.append({"role": "assistant", "content": generated_code})
                messages.append({
                    "role": "user",
                    "content": "You did not output any valid code. You must output the full test code inside a markdown block. Do not apologize or explain."
                })
            continue

        # Auto-correct hallucinated module names (DeepSeek often invents 'sample_module')
        if language == "python":
            import ast
            module_name = "module_under_test"
            try:
                tree = ast.parse(clean_code)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        if node.module not in ['typing', 'collections', 'pytest', 'unittest', 'math', 'os', 'sys']:
                            if node.module != module_name:
                                clean_code = re.sub(rf"from\s+{node.module}\s+import", f"from {module_name} import", clean_code)
            except Exception:
                pass
            
            clean_code = clean_code.replace("sample_module", module_name)

        best_code = clean_code
        
        status = f"🔄 Self-Reflection Attempt {attempt + 1}/{max_retries + 1}: Running tests in Sandbox..."
        logger.info(status)
        yield (status, best_code.replace("module_under_test", Path(file_name).stem), {})

        # Run Sandbox
        dump_trace(f"ATTEMPT {attempt + 1} - GENERATED CODE", clean_code.replace("module_under_test", Path(file_name).stem))
        result = sandbox.run_test(file_name, source_code, clean_code)
        dump_trace(f"ATTEMPT {attempt + 1} - SANDBOX RESULT", f"Success: {result.success}\nStdout:\n{result.stdout}\nStderr:\n{result.stderr}\nError Log:\n{result.error_log}\nCoverage: {result.coverage}")
        
        # We save the best result so we can return it if we run out of retries
        best_result = {"success": result.success, "coverage": result.coverage, "missing_lines": result.missing_lines}
        
        if result.success:
            coverage = result.coverage or 0.0
            if coverage >= target_coverage:
                msg = f"✅ Sandbox passed! Coverage {coverage:.1f}% >= target {target_coverage}%. Returning perfect code."
                logger.info(msg)
                yield (msg, clean_code.replace("module_under_test", Path(file_name).stem), best_result)
                return
            else:
                msg = f"⚠️ Sandbox passed, but coverage ({coverage:.1f}%) < target ({target_coverage}%). Requesting more tests..."
                logger.warning(msg)
                yield (msg, clean_code.replace("module_under_test", Path(file_name).stem), best_result)
                
                if attempt < max_retries:
                    missing_str = f" Lines missing coverage: {result.missing_lines}." if result.missing_lines else ""
                    messages.append({"role": "assistant", "content": generated_code})
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Your tests passed, but the code coverage is only {coverage:.1f}%. The target is {target_coverage}%.{missing_str}\n"
                            f"Please WRITE ADDITIONAL TESTS to cover these missing lines or branches.\n"
                            f"MANDATORY: Keep all the existing tests intact. Just append new tests to increase coverage.\n"
                            f"Output the ENTIRE, complete test file inside a single markdown block."
                        )
                    })
                else:
                    msg = f"❌ Max retries reached. Returning code with {coverage:.1f}% coverage."
                    logger.warning(msg)
                    yield (msg, clean_code.replace("module_under_test", Path(file_name).stem), best_result)
                    return
        else:
            err_str = result.error_log.strip()
            err_snippet = "Unknown error"
            for line in reversed(err_str.split('\n')):
                line = line.strip()
                if line and not line.startswith('=') and not line.startswith('-') and not line.startswith('!'):
                    err_snippet = line
                    if "ERROR" in line or "Error" in line or "Exception" in line:
                        break
            if len(err_snippet) > 80:
                err_snippet = err_snippet[:80] + "..."
                
            msg = f"⚠️ Sandbox failed ({err_snippet}). Analysing..."
            logger.warning(msg)
            yield (msg, clean_code.replace("module_under_test", Path(file_name).stem), best_result)
            
            if attempt < max_retries:
                # Add to message history for reflection
                messages.append({"role": "assistant", "content": generated_code})
                messages.append({
                    "role": "user", 
                    "content": (
                        f"Your generated test code failed when executed. Here is the error log:\n"
                        f"```\n{result.error_log[-2000:]}\n```\n"
                        f"Analyze the error. If it is an AssertionError, your test expects the wrong output; FIX YOUR TEST to match the source code's actual behavior.\n\n"
                        f"MANDATORY RULES FOR YOUR FIX:\n"
                        f"1. The FIRST line MUST be `import pytest`\n"
                        f"2. The SECOND line MUST be `from module_under_test import ...` (import all needed symbols)\n"
                        f"3. NEVER use any other module name. ONLY `module_under_test`.\n"
                        f"4. Use `pytest.raises(ExceptionType)` for exception testing.\n"
                        f"5. Output the ENTIRE, complete, standalone test file from start to finish.\n"
                        f"6. Do NOT output partial snippets, explanations, or prose. Just the code inside a single markdown block (```{language})."
                    )
                })
            else:
                msg = "❌ Max retries reached. Returning the best effort code."
                logger.error(msg)
                yield (msg, clean_code.replace("module_under_test", Path(file_name).stem), best_result)
                return
