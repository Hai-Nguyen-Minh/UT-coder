import importlib
import sys
import types
from types import SimpleNamespace

import pytest
from core.sandbox.base import SandboxResult


@pytest.fixture
def generator_module(monkeypatch):
    """Import generator without requiring optional Chroma/LangChain packages."""
    import core

    code_parser = types.ModuleType("core.code_parser")
    code_parser.detect_language = lambda _name: "python"
    code_parser.parse_code = lambda file_name, source: [
        SimpleNamespace(page_content=source, metadata={"source": file_name})
    ]
    config = types.ModuleType("core.config")
    config.get_config = lambda: {
        "languages": {"python": {"test_framework": "pytest"}}
    }
    llm_module = types.ModuleType("core.llm")
    llm_module.get_llm = lambda: None
    vectorstore = types.ModuleType("core.vectorstore")
    vectorstore.index_documents = lambda _docs, _collection: None
    vectorstore.similarity_search = lambda **_kwargs: []
    monkeypatch.setitem(sys.modules, "core.code_parser", code_parser)
    monkeypatch.setitem(sys.modules, "core.config", config)
    monkeypatch.setitem(sys.modules, "core.llm", llm_module)
    monkeypatch.setitem(sys.modules, "core.vectorstore", vectorstore)
    monkeypatch.setattr(core, "vectorstore", vectorstore, raising=False)
    sys.modules.pop("core.generator", None)
    imported = importlib.import_module("core.generator")
    yield imported
    sys.modules.pop("core.generator", None)


SOURCE = """
class Service:
    def __init__(self, repository):
        self.repository = repository

    def load(self, item_id):
        return self.repository.get(item_id)
"""

PROJECT_FILES = {
    "repository.py": """
class Repository:
    def get(self, item_id):
        raise NotImplementedError

SECRET_CONTEXT = 'retrieved-support-module'
""",
}


class _Chunk:
    content = """```python
import pytest
from module_under_test import Service

def test_load():
    repository = type("Repo", (), {"get": lambda self, item_id: "ok"})()
    assert Service(repository).load(1) == "ok"
```"""


class _FakeLlm:
    def __init__(self):
        self.messages = []

    def stream(self, messages):
        self.messages.append(messages)
        return iter([_Chunk()])


class _FakeSandbox:
    def __init__(self):
        self.project_files_seen = None

    def run_test(self, _file_name, _source_code, _test_code, *, project_files=None):
        self.project_files_seen = project_files
        return SandboxResult(
            success=True,
            stdout="1 passed",
            stderr="",
            coverage=100.0,
            missing_lines=[],
            execution_status="tests_passed",
            coverage_valid=True,
            tests_collected=1,
            tests_passed=1,
            tests_failed=0,
        )


def _install_runtime(monkeypatch, generator):
    import core.behavioral_testing
    import core.sandbox

    fake_llm = _FakeLlm()
    fake_sandbox = _FakeSandbox()
    monkeypatch.setattr(generator, "get_llm", lambda: fake_llm)
    monkeypatch.setattr(core.sandbox, "get_sandbox", lambda _language: fake_sandbox)
    monkeypatch.setattr(
        core.behavioral_testing,
        "build_behavioral_candidate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("project-aware generation must bypass behavioral probing")
        ),
    )
    return fake_llm, fake_sandbox


def test_no_rag_never_touches_vectorstore_and_keeps_static_router(
    monkeypatch, generator_module
):
    generator = generator_module
    fake_llm, fake_sandbox = _install_runtime(monkeypatch, generator)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("the no-RAG arm touched the vector store")

    monkeypatch.setattr(generator, "index_code", forbidden)
    monkeypatch.setattr(generator.vs, "index_documents", forbidden)
    monkeypatch.setattr(generator.vs, "similarity_search", forbidden)

    events = list(
        generator.generate_with_reflection(
            "service.py",
            SOURCE,
            max_retries=0,
            rag_enabled=False,
            project_files=PROJECT_FILES,
        )
    )

    prompt = fake_llm.messages[0][1]["content"]
    assert "STATIC STRATEGY ROUTER" in prompt
    assert "retrieved-support-module" not in prompt
    assert fake_sandbox.project_files_seen == PROJECT_FILES
    assert events[-1][2]["rag_enabled"] is False
    assert events[-1][2]["rag"]["project_context_chunks"] == 0


def test_project_rag_indexes_support_files_and_records_retrieval(
    monkeypatch, generator_module
):
    generator = generator_module
    fake_llm, fake_sandbox = _install_runtime(monkeypatch, generator)
    support_doc = SimpleNamespace(
        page_content=PROJECT_FILES["repository.py"],
        metadata={"source": "repository.py"},
    )
    indexed = []

    monkeypatch.setattr(
        generator,
        "parse_code",
        lambda file_name, source: [
            SimpleNamespace(page_content=source, metadata={"source": file_name})
        ],
    )
    monkeypatch.setattr(
        generator,
        "index_code",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("project RAG must index the support corpus, not the target alone")
        ),
    )
    monkeypatch.setattr(
        generator.vs,
        "index_documents",
        lambda docs, collection: indexed.append((list(docs), collection)),
    )

    def similarity_search(*, collection_name, **_kwargs):
        if collection_name.endswith("project_context"):
            return [support_doc]
        return []

    monkeypatch.setattr(generator.vs, "similarity_search", similarity_search)
    embed_rag = types.ModuleType("core.dataset.embed_rag")
    embed_rag.get_semantic_description = lambda _source: "service repository"
    monkeypatch.setitem(sys.modules, "core.dataset.embed_rag", embed_rag)

    events = list(
        generator.generate_with_reflection(
            "service.py",
            SOURCE,
            max_retries=0,
            rag_enabled=True,
            rag_strict=True,
            project_files=PROJECT_FILES,
            project_context_k=4,
        )
    )

    prompt = fake_llm.messages[0][1]["content"]
    assert indexed and indexed[0][0][0].metadata["source"] == "repository.py"
    assert "retrieved-support-module" in prompt
    assert fake_sandbox.project_files_seen == PROJECT_FILES
    assert events[-1][2]["rag"]["project_documents_indexed"] == 1
    assert events[-1][2]["rag"]["project_context_chunks"] == 1
