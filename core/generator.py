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
from typing import Generator, Mapping

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
        "- MANDATORY: The second line MUST import the symbols from `module_under_test` (e.g. `from module_under_test import func1, func2`).\n"
        "- NEVER use any other module name. ONLY use `module_under_test`.\n"
        "- Use `pytest.raises(...)` for testing exceptions.\n"
        "- Use `pytest` fixtures and parametrize where it adds value.\n"
        "- Prefix all test functions with `test_`.\n"
        "- Use `unittest.mock.patch` for mocking.\n"
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


def _failed_python_targets(error_log: str) -> list[str]:
    """Extract reproducible pytest node ids, including setup/teardown errors."""
    from core.ast_patcher import failed_pytest_targets

    return failed_pytest_targets(error_log)


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
        f"- IMPORTANT: If the source code uses `requests`, `urllib`, or File I/O (`open`), you MUST mock them using `unittest.mock.patch` or `pytest-mock`.\n"
        f"- For filesystem tests, use pytest `tmp_path`; never write to placeholder paths such as `path/to/...`.\n"
        f"- If datetime is needed, use fixed values such as `datetime(2023, 1, 1)`; NEVER use `datetime.now()`, `utcnow()`, or `today()`.\n"
        f"- THINK BEFORE YOU CODE: Open a `<thought> ... </thought>` block to analyze the source code, identify edge cases, and plan your tests (including necessary mocks). Then, output the test code.\n"
        f"- Output ONLY the test file source code inside a markdown code block (```) after your thought block.\n"
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
    target_coverage: float = 80.0,
    *,
    rag_enabled: bool = True,
    rag_strict: bool = False,
    project_files: Mapping[str, str] | None = None,
    project_context_k: int = 4,
) -> Generator[tuple[str, str, dict], None, None]:
    """
    Generate unit tests with an inner reflection loop.
    Generates code, runs it in the Sandbox. If it fails or coverage is below target, feeds the error back to the LLM.

    ``rag_enabled=False`` is a hard ablation boundary: no source indexing,
    project-context search, or few-shot retrieval is performed. ``project_files``
    contains support modules available to the sandbox and, with RAG enabled,
    provides the project-context retrieval corpus.
    Returns: (status_message, generated_code, sandbox_result_dict)
    """
    from core.sandbox import get_sandbox
    from core.sandbox.base import (
        SandboxInfrastructureError,
        detect_sandbox_infrastructure_error,
    )
    import re

    language = detect_language(file_name)
    sandbox = get_sandbox(language)
    
    # 1. Initial generation (no stream)
    llm = get_llm()
    
    # Reuse prompts from stream method
    cfg = get_config().get("languages", {}).get(language, {})
    framework = cfg.get("test_framework", "Unknown")
    lang_instructions = _LANG_INSTRUCTIONS.get(language, "")
    project_import_rule = (
        "Import target APIs from `module_under_test`. You MAY import support "
        "types/constants from the exact internal module names visible in the "
        "target imports or retrieved project context. NEVER invent a module name."
        if language == "python" and project_files
        else (
            "Import ONLY top-level functions/classes from `module_under_test`. "
            "Do NOT import or test inner/nested functions directly. Example: "
            "`from module_under_test import main_func`"
        )
    )
    if language == "python" and project_files:
        lang_instructions = (
            "- MANDATORY: The first line of the test file MUST be `import pytest`.\n"
            "- Import target APIs from `module_under_test`.\n"
            "- Support types/constants MAY be imported from exact project module "
            "names visible in the supplied context; NEVER invent modules.\n"
            "- Use `pytest.raises(...)` for testing exceptions.\n"
            "- Use pytest fixtures and parametrize where it adds value.\n"
            "- Prefix all test functions with `test_`.\n"
            "- Use `unittest.mock.patch` for mocking.\n"
        )

    if project_context_k < 1:
        raise ValueError("project_context_k must be at least 1")

    # Source analysis powers the static strategy router independently of RAG.
    # The no-RAG arm therefore retains object/mock routing without touching
    # ChromaDB.
    source_contract = {}
    desired_strategy = None
    if language == "python":
        try:
            from core.source_analyzer import analyze_python_source

            source_contract = analyze_python_source(source_code)
            desired_strategy = (
                "behavioral_probe"
                if source_contract.get("behavioral_eligibility", {}).get("eligible")
                else "codegen_with_mocks_or_objects"
            )
        except Exception as exc:
            logger.debug("Could not analyze Python source contract: %s", exc)

    rag_metadata = {
        "rag_enabled": rag_enabled,
        "project_documents_indexed": 0,
        "project_context_chunks": 0,
        "fewshot_candidates": 0,
        "fewshot_examples_used": 0,
    }

    # Retrieve project/source context only in the RAG arm.
    context_block = ""
    if rag_enabled:
        try:
            if project_files:
                project_docs = []
                for project_file_name, project_source in project_files.items():
                    if not isinstance(project_file_name, str) or not isinstance(project_source, str):
                        raise TypeError("project_files must map file names to source strings")
                    project_docs.extend(parse_code(project_file_name, project_source))
                rag_metadata["project_documents_indexed"] = len(project_docs)

                docs = []
                if project_docs:
                    col_name = _sanitize_collection_name(f"{file_name}_project_context")
                    logger.info(
                        "Indexing %d support-file chunks for '%s' into '%s'",
                        len(project_docs),
                        file_name,
                        col_name,
                    )
                    vs.index_documents(project_docs, col_name)
                    docs = vs.similarity_search(
                        query=source_code,
                        collection_name=col_name,
                        k=project_context_k,
                    )
            else:
                # Preserve single-file RAG for existing API and benchmark callers.
                col_name = index_code(file_name, source_code)
                docs = vs.similarity_search(
                    query=source_code,
                    collection_name=col_name,
                    k=project_context_k,
                )

            rag_metadata["project_context_chunks"] = len(docs)
            if rag_strict and not docs:
                raise RuntimeError("strict RAG retrieved no project context")

            if docs:
                if project_files:
                    context_joined = "\n\n---\n\n".join(
                        f"File: {doc.metadata.get('source', 'unknown')}\n"
                        f"{doc.page_content}"
                        for doc in docs
                    )
                    context_block = (
                        "\n\nRetrieved project context (support modules available "
                        f"to the test runtime):\n{context_joined}"
                    )
                else:
                    # Preserve the pre-ablation single-file prompt byte-for-byte
                    # so an unfinished main benchmark can resume comparably.
                    context_joined = "\n\n".join(
                        doc.page_content for doc in docs
                    )
                    context_block = f"\n\nContext from other files:\n{context_joined}"
        except Exception as exc:
            if rag_strict:
                raise RuntimeError(
                    f"strict project-context RAG failed for {file_name}: {exc}"
                ) from exc
            logger.warning("Project-context RAG unavailable for '%s': %s", file_name, exc)

    system_prompt = (
        f"You are an expert at writing Characterization Tests in {language}.\n"
        f"Your goal is to write tests that capture the EXACT CURRENT BEHAVIOR of the source code, even if the source code contains mathematical or logical bugs.\n"
        f"Do not try to write tests for what the code 'should' do. Test what it 'actually' outputs.\n\n"
        f"Test framework: **{framework}**\n\n"
        f"Requirements:\n"
        f"{lang_instructions}"
        f"- Cover ALL public functions, methods, and classes.\n"
        f"- Include happy-path, edge case, boundary, and error/exception tests.\n"
        f"- DO NOT use excessively large inputs (e.g., loops > 10000, N > 15, arrays > 10000 elements) to prevent execution timeouts.\n"
        f"- DO NOT use `unittest.TestCase` or `self.assertEqual()`. You MUST use pure pytest assertions (`assert ACTUAL == EXPECTED`).\n"
        f"- For filesystem tests, use pytest `tmp_path`; never write to placeholder paths such as `path/to/...`.\n"
        f"- If datetime is needed, use fixed values such as `datetime(2023, 1, 1)`; NEVER use `datetime.now()`, `utcnow()`, or `today()`.\n"
        f"- Write descriptive test names that read like sentences.\n"
        f"- Add inline comments for non-obvious test logic.\n"
        f"- Output ONLY the test file source code inside a markdown code block (```). "
        f"Do not include any prose or explanation before or after the code block.\n"
        f"- The output must be valid, executable {language} code."
    )

    # Retrieve few-shot examples (source→test pairs) from the seed collection
    fewshot_block = ""
    try:
        if not rag_enabled:
            raise RuntimeError("RAG disabled for this generation")
        filter_dict = {"language": language}

        from core.dataset.embed_rag import get_semantic_description

        # Match query semantic space with Nomic document semantics
        semantic_query = f"search_query: {get_semantic_description(source_code)}"

        fewshot_collection = (
            "utcoder_python_fewshot_v2" if language == "python"
            else "utcoder_fewshot_examples"
        )
        fewshot_snippets = vs.similarity_search(
            query=semantic_query,
            collection_name=fewshot_collection,
            k=4,
            filter=filter_dict
        )
        if language == "python" and not fewshot_snippets:
            # Safe migration fallback until the server rebuilds the v2 collection.
            fewshot_snippets = vs.similarity_search(
                query=semantic_query,
                collection_name="utcoder_fewshot_examples",
                k=2,
            )
        rag_metadata["fewshot_candidates"] = len(fewshot_snippets)
        if fewshot_snippets:
            if desired_strategy:
                fewshot_snippets.sort(
                    key=lambda doc: doc.metadata.get("strategy") != desired_strategy
                )
            examples = []
            for d in fewshot_snippets:
                src = d.metadata.get("source", "")
                tst = d.metadata.get("tests", "")
                if src and tst:
                    # One concise structural analogue is safer for 7B/8B models
                    # than several examples that crowd the 8K context window.
                    src = src[:3000]
                    tst = tst[:5000]
                    examples.append(f"**Source Code:**\n```python\n{src}\n```\n\n**Reference pytest patterns:**\n```python\n{tst}\n```")
                    break

            if examples:
                rag_metadata["fewshot_examples_used"] = len(examples)
                fewshot_joined = "\n\n---\n\n".join(examples)
                fewshot_block = (
                    f"\n\nHere are reference examples of correct source→test pairs. "
                    f"Follow the same style, import pattern, "
                    f"and testing patterns:\n\n{fewshot_joined}"
                )

    except Exception as exc:
        if rag_enabled and rag_strict:
            raise RuntimeError(f"strict few-shot RAG failed for {file_name}: {exc}") from exc
        if rag_enabled:
            logger.warning("Few-shot RAG unavailable for '%s': %s", file_name, exc)

    strategy_block = ""
    if language == "python":
        try:
            if not source_contract:
                from core.source_analyzer import analyze_python_source
                source_contract = analyze_python_source(source_code)
            eligibility = source_contract.get("behavioral_eligibility", {})
            if not eligibility.get("eligible", False):
                classes = [item.get("name") for item in source_contract.get("classes", [])]
                protocols = {
                    item.get("name"): item.get("parameter_attributes", [])
                    for item in source_contract.get("functions", [])
                    if item.get("parameter_attributes")
                }
                strategy_block = (
                    "\n\nSTATIC STRATEGY ROUTER:\n"
                    "This module was intentionally excluded from JSON behavioral probing. "
                    f"Reasons: {', '.join(eligibility.get('reasons', []))}.\n"
                    f"Public/custom classes detected: {classes}.\n"
                    f"Injected parameter protocols detected: {protocols}.\n"
                    "For custom objects, instantiate the real public class with the smallest valid constructor inputs. "
                    "For injected protocols, use unittest.mock.MagicMock and configure only methods actually accessed by the source. "
                    "For imported services, patch the name in module_under_test (the lookup namespace), and never perform real network, file, database, process, or environment operations."
                )
        except Exception as exc:
            logger.debug("Could not build static strategy block: %s", exc)

    user_prompt = (
        f"Generate comprehensive {framework} unit tests for this {language} file: `{file_name}`\n\n"
        f"CRITICAL RULES (VIOLATION = INSTANT FAILURE):\n"
        f"1. The test file MUST start with `import {framework}` on the very first line.\n"
        f"2. {project_import_rule}\n"
        f"3. NEVER use the original filename `{Path(file_name).stem}` as module name. ALWAYS use `module_under_test`.\n"
        f"4. Use `{framework}.raises(ExceptionType)` for exception tests (NOT try/except).\n"
        f"5. DO NOT use `unittest.TestCase` or `self.assertEqual()`. You MUST use pure pytest assertions (`assert ACTUAL == EXPECTED`).\n\n"
        f"Source Code:\n```{language}\n{source_code}\n```"
        f"{fewshot_block}"
        f"{context_block}"
        f"{strategy_block}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt},
    ]

    logger.info(f"Starting Reflection Loop for {file_name} (max_retries={max_retries}, target_cov={target_coverage}%)")
    dump_trace(f"REFLECTION LOOP START: {file_name}", f"System Prompt:\n{system_prompt}\n\nUser Prompt:\n{user_prompt}")
    
    best_code = ""
    best_result = None
    use_targeted_reflection = False
    last_patch_was_noop = False
    failed_funcs: list[str] = []
    coverage_expansion_used = False
    best_passing_code = ""
    best_passing_result = None
    best_passing_coverage = -1.0
    
    for attempt in range(max_retries + 1):
        status = f"🔄 Self-Reflection Attempt {attempt + 1}/{max_retries + 1}: Generating code..."
        logger.info(status)
        
        generated_code = ""

        # On unseen Python source, the model chooses inputs while the server
        # observes actual values/exceptions and deterministically emits pytest.
        # The original full-code generator remains the fallback.
        if language == "python" and attempt == 0 and not project_files:
            try:
                import json
                from core.behavioral_testing import build_behavioral_candidate

                behavioral_code, behavioral_diagnostics = build_behavioral_candidate(
                    llm,
                    file_name,
                    source_code,
                    max_cases=10,
                )
                generated_code = behavioral_code
                dump_trace(
                    f"ATTEMPT {attempt + 1} - BEHAVIORAL PLAN",
                    json.dumps(behavioral_diagnostics, ensure_ascii=False, indent=2),
                )
                if generated_code:
                    behavioral_status = (
                        f"{status} Behavioral probes produced "
                        f"{len(behavioral_diagnostics.get('observations', []))} observed case(s)."
                    )
                    yield (
                        behavioral_status,
                        generated_code.replace("module_under_test", Path(file_name).stem),
                        {},
                    )
                else:
                    logger.info(
                        "Behavioral generation unavailable for '%s': %s. Falling back to full-code generation.",
                        file_name,
                        behavioral_diagnostics.get("reason", "unknown reason"),
                    )
            except Exception as exc:
                logger.warning("Behavioral generation failed for '%s': %s", file_name, exc)

        if not generated_code:
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
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                    {"role": "assistant", "content": best_code},
                    {"role": "user", "content": "You did not output any valid code. You must output the full test code inside a markdown block. Do not apologize or explain."}
                ]
            continue

        # Auto-correct hallucinated module names (DeepSeek often invents 'sample_module')
        if language == "python":
            module_name = "module_under_test"
            clean_code = clean_code.replace("sample_module", module_name)
            from core.test_normalizer import normalize_python_tests
            clean_code = normalize_python_tests(clean_code, source_code)

        if use_targeted_reflection and language == "python":
            import core.ast_patcher as ast_patcher
            # Patch the best_code with the newly generated function(s)
            patched = ast_patcher.patch_functions(best_code, clean_code, failed_funcs)
            patched = normalize_python_tests(patched, source_code)
            last_patch_was_noop = patched.strip() == best_code.strip()
            best_code = patched
            msg = (
                "⚠️ Targeted Reflection produced no AST change; next retry will request a full rewrite."
                if last_patch_was_noop
                else "🔧 Targeted Reflection applied (AST Patching successful)"
            )
            logger.info(msg)
            # Yield so user can see it patched
            yield (msg, best_code.replace("module_under_test", Path(file_name).stem), {})
        else:
            best_code = clean_code
            last_patch_was_noop = False
        
        status = f"🔄 Self-Reflection Attempt {attempt + 1}/{max_retries + 1}: Running tests in Sandbox..."
        logger.info(status)
        yield (status, best_code.replace("module_under_test", Path(file_name).stem), {})

        # Run Sandbox
        dump_trace(f"ATTEMPT {attempt + 1} - GENERATED CODE", best_code.replace("module_under_test", Path(file_name).stem))
        result = sandbox.run_test(
            file_name,
            source_code,
            best_code,
            project_files=project_files,
        )
        dump_trace(f"ATTEMPT {attempt + 1} - SANDBOX RESULT", f"Success: {result.success}\nExecution status: {result.execution_status}\nCoverage valid: {result.coverage_valid}\nTests collected/passed/failed: {result.tests_collected}/{result.tests_passed}/{result.tests_failed}\nStdout:\n{result.stdout}\nStderr:\n{result.stderr}\nError Log:\n{result.error_log}\nCoverage: {result.coverage}")
        
        # We save the best result so we can return it if we run out of retries
        infrastructure_error = detect_sandbox_infrastructure_error(
            result.stderr, result.error_log, result.stdout
        )
        best_result = {
            "success": result.success,
            "coverage": result.coverage,
            "missing_lines": result.missing_lines,
            "execution_status": result.execution_status,
            "coverage_valid": result.coverage_valid,
            "tests_collected": result.tests_collected,
            "tests_passed": result.tests_passed,
            "tests_failed": result.tests_failed,
            "error_log": (result.error_log or "")[-8000:],
            "stderr": (result.stderr or "")[-8000:],
            "rag_enabled": rag_enabled,
            "rag": dict(rag_metadata),
            "infrastructure_error": infrastructure_error,
            "meets_coverage": bool(
                result.success and (result.coverage or 0.0) >= target_coverage
            ),
        }

        if infrastructure_error:
            msg = f"🛑 Sandbox infrastructure failure: {infrastructure_error}"
            logger.error(msg)
            yield (
                msg,
                best_code.replace("module_under_test", Path(file_name).stem),
                best_result,
            )
            raise SandboxInfrastructureError(infrastructure_error)
        
        if result.success:
            coverage = result.coverage or 0.0
            if coverage > best_passing_coverage:
                best_passing_code = best_code
                best_passing_result = dict(best_result)
                best_passing_coverage = coverage
            if coverage >= target_coverage:
                best_result["meets_coverage"] = True
                msg = f"✅ Sandbox passed! Coverage {coverage:.1f}% >= target {target_coverage}%. Returning perfect code."
                logger.info(msg)
                yield (msg, best_code.replace("module_under_test", Path(file_name).stem), best_result)
                return
            else:
                # One bounded expansion uses exact missing lines. This avoids
                # an unbounded, token-heavy coverage feedback loop.
                if (
                    language == "python"
                    and result.missing_lines
                    and not coverage_expansion_used
                    and not project_files
                ):
                    coverage_expansion_used = True
                    try:
                        import json
                        from core.behavioral_testing import (
                            build_behavioral_candidate,
                            merge_pytest_files,
                        )

                        additional_code, coverage_diagnostics = build_behavioral_candidate(
                            llm,
                            file_name,
                            source_code,
                            max_cases=10,
                            missing_lines=result.missing_lines,
                        )
                        dump_trace(
                            f"ATTEMPT {attempt + 1} - COVERAGE EXPANSION PLAN",
                            json.dumps(
                                coverage_diagnostics,
                                ensure_ascii=False,
                                indent=2,
                            ),
                        )
                        expanded_code = merge_pytest_files(best_code, additional_code)
                        if expanded_code.strip() != best_code.strip():
                            expansion_status = (
                                f"🎯 Tests pass at {coverage:.1f}%; running one targeted "
                                f"coverage expansion for missing lines {result.missing_lines}."
                            )
                            logger.info(expansion_status)
                            yield (
                                expansion_status,
                                expanded_code.replace(
                                    "module_under_test", Path(file_name).stem
                                ),
                                best_result,
                            )
                            expanded_result = sandbox.run_test(
                                file_name,
                                source_code,
                                expanded_code,
                                project_files=project_files,
                            )
                            dump_trace(
                                f"ATTEMPT {attempt + 1} - COVERAGE EXPANSION RESULT",
                                f"Success: {expanded_result.success}\n"
                                f"Stdout:\n{expanded_result.stdout}\n"
                                f"Stderr:\n{expanded_result.stderr}\n"
                                f"Error Log:\n{expanded_result.error_log}\n"
                                f"Coverage: {expanded_result.coverage}",
                            )
                            expansion_infrastructure_error = (
                                detect_sandbox_infrastructure_error(
                                    expanded_result.stderr,
                                    expanded_result.error_log,
                                    expanded_result.stdout,
                                )
                            )
                            if expansion_infrastructure_error:
                                raise SandboxInfrastructureError(
                                    expansion_infrastructure_error
                                )

                            expanded_coverage = expanded_result.coverage or 0.0
                            if expanded_result.success and expanded_coverage > coverage:
                                best_code = expanded_code
                                result = expanded_result
                                coverage = expanded_coverage
                                best_result = {
                                    "success": True,
                                    "coverage": expanded_result.coverage,
                                    "missing_lines": expanded_result.missing_lines,
                                    "execution_status": expanded_result.execution_status,
                                    "coverage_valid": expanded_result.coverage_valid,
                                    "tests_collected": expanded_result.tests_collected,
                                    "tests_passed": expanded_result.tests_passed,
                                    "tests_failed": expanded_result.tests_failed,
                                    "error_log": (expanded_result.error_log or "")[-8000:],
                                    "stderr": (expanded_result.stderr or "")[-8000:],
                                    "rag_enabled": rag_enabled,
                                    "rag": dict(rag_metadata),
                                    "infrastructure_error": None,
                                    "meets_coverage": coverage >= target_coverage,
                                }
                                if coverage > best_passing_coverage:
                                    best_passing_code = best_code
                                    best_passing_result = dict(best_result)
                                    best_passing_coverage = coverage
                                if coverage >= target_coverage:
                                    msg = (
                                        f"✅ Coverage expansion passed! Coverage "
                                        f"{coverage:.1f}% >= target {target_coverage}%."
                                    )
                                    logger.info(msg)
                                    yield (
                                        msg,
                                        best_code.replace(
                                            "module_under_test", Path(file_name).stem
                                        ),
                                        best_result,
                                    )
                                    return
                    except SandboxInfrastructureError:
                        raise
                    except Exception as exc:
                        logger.warning("Coverage expansion skipped: %s", exc)

                if best_passing_code and best_passing_coverage > coverage:
                    best_code = best_passing_code
                    best_result = dict(best_passing_result)
                    coverage = best_passing_coverage
                best_result["meets_coverage"] = False
                if attempt < max_retries:
                    missing_lines = list(best_result.get("missing_lines", []))
                    msg = (
                        f"🔁 Pytest passed but coverage {coverage:.1f}% is below "
                        f"{target_coverage}%. Starting coverage self-reflection for "
                        f"missing lines {missing_lines}."
                    )
                    logger.warning(msg)
                    yield (
                        msg,
                        best_code.replace("module_under_test", Path(file_name).stem),
                        best_result,
                    )
                    use_targeted_reflection = False
                    last_patch_was_noop = False
                    messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                        {"role": "assistant", "content": best_code},
                        {"role": "user", "content": (
                            f"All tests in the current file PASS, but source coverage is only "
                            f"{coverage:.1f}% and must reach at least {target_coverage}%.\n"
                            f"Coverage reports these source lines as missing: {missing_lines}.\n\n"
                            f"Preserve EVERY existing passing test exactly. Do not delete, rename, "
                            f"weaken, or change its assertions. Add new deterministic tests that "
                            f"execute the missing branches and lines. Use small inputs, fixed dates, "
                            f"pytest tmp_path for filesystem work, and mocks for external dependencies.\n"
                            f"Return the ENTIRE complete standalone test file, including all existing "
                            f"tests plus the new tests, inside one markdown code block."
                        )},
                    ]
                    continue

                fallback_code = best_passing_code or best_code
                fallback_result = best_passing_result or best_result
                fallback_result["meets_coverage"] = False
                msg = (
                    f"⚠️ Pytest passed, but best coverage "
                    f"{max(coverage, best_passing_coverage):.1f}% is below the required "
                    f"{target_coverage}% gate after all reflection attempts. "
                    f"Benchmark result is not accepted."
                )
                logger.warning(msg)
                yield (
                    msg,
                    fallback_code.replace("module_under_test", Path(file_name).stem),
                    fallback_result,
                )
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
            yield (msg, best_code.replace("module_under_test", Path(file_name).stem), best_result)
            
            if attempt < max_retries:
                use_targeted_reflection = False
                failed_code = ""

                # Smart Log Parsing
                match = re.search(r"(={3,}\s*(?:FAILURES|ERRORS)\s*={3,}.*?)(?:={3,}\s*short test summary info\s*={3,}|$)", result.error_log, re.DOTALL)
                if match:
                    smart_error_log = match.group(1).strip()
                else:
                    smart_error_log = result.error_log[-4000:].strip()

                if language == "python" and not last_patch_was_noop:
                    failed_funcs = _failed_python_targets(result.error_log)
                    if failed_funcs:
                        import core.ast_patcher as ast_patcher
                        failed_code = ast_patcher.extract_functions(best_code, failed_funcs)
                        if failed_code:
                            use_targeted_reflection = True

                if use_targeted_reflection:
                    msg = f"🎯 Targeted Reflection triggered for {len(failed_funcs)} function(s)"
                    logger.info(msg)
                    yield (msg, best_code.replace("module_under_test", Path(file_name).stem), best_result)

                    messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                        {"role": "assistant", "content": "I have generated the tests."},
                        {"role": "user", "content": (
                            f"The following test functions failed:\n```python\n{failed_code}\n```\n"
                            f"Error log:\n```\n{smart_error_log}\n```\n"
                            f"CRITICAL INSTRUCTION 1: If the error is an AssertionError, you MUST change your test's expected output to exactly match the ACTUAL output shown in the error log!\n"
                            f"In pytest, `assert 3 == 10` means ACTUAL was 3 and EXPECTED was 10. You MUST change your test to `expected_output = 3`.\n"
                            f"DO NOT calculate the math yourself. BLINDLY COPY the actual value from the error log into your test.\n"
                            f"CRITICAL INSTRUCTION 2: If the error is an unhandled exception (e.g., TypeError, IndexError, ValueError) raised by the source code, you MUST modify the test to expect that exception using `with pytest.raises(ExceptionType):`.\n"
                            f"Please rewrite ONLY these test functions to fix the assertions or exceptions. Do not output the rest of the file. Output the fixed functions inside a single markdown block."
                        )}
                    ]
                else:
                    # Reset message history for reflection
                    messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                        {"role": "assistant", "content": best_code},
                        {"role": "user", "content": (
                            f"Your generated test code failed when executed. Here is the error log:\n"
                            f"```\n{smart_error_log}\n```\n"
                            f"Analyze the error. If you see an AssertionError (e.g. 'assert ACTUAL == EXPECTED'), your test expects the wrong output. YOU MUST CHANGE your test's expected output to exactly match the ACTUAL output shown in the error log!\n"
                            f"CRITICAL HINT 1: If the error log shows an unexpected Exception (like RecursionError, TypeError, IndexError) thrown by the source code, DO NOT TRY TO FIX THE SOURCE CODE. The source code has a bug. You MUST rewrite your test to EXPECT that exact exception using `pytest.raises(ExactException)` so the test passes!\n"
                            f"CRITICAL HINT 2: If the error is 'ConnectionError', 'Timeout', or 'FileNotFoundError', you forgot to MOCK the external dependency. Rewrite the test using `@patch` to mock it!\n\n"
                            f"MANDATORY RULES FOR YOUR FIX:\n"
                            f"1. The FIRST line MUST be `import pytest`\n"
                            f"2. The SECOND line MUST import all needed symbols from `module_under_test`\n"
                            f"3. NEVER use any other module name. ONLY `module_under_test`.\n"
                            f"4. Use `pytest.raises(ExceptionType)` for exception testing.\n"
                            f"5. Output the ENTIRE, complete, standalone test file from start to finish.\n"
                            f"6. Do NOT output partial snippets. Just the code inside a single markdown block (```{language})."
                        )}
                    ]
            else:
                if best_passing_code and best_passing_result:
                    best_code = best_passing_code
                    best_result = dict(best_passing_result)
                    best_result["meets_coverage"] = False
                    msg = (
                        "❌ Max retries reached after a failing reflection candidate. "
                        "Returning the best previously passing test suite."
                    )
                else:
                    msg = "❌ Max retries reached. Returning the best effort code."
                logger.error(msg)
                yield (msg, best_code.replace("module_under_test", Path(file_name).stem), best_result)
                return
