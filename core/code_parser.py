"""
core/code_parser.py
-------------------
Language detection and code chunking utilities.
Maps file extensions → language keys, then uses LangChain's
RecursiveCharacterTextSplitter with language-aware separators.
"""

from pathlib import Path
from typing import List

from langchain_text_splitters import Language, RecursiveCharacterTextSplitter
from langchain_core.documents import Document

# Supported languages (matches config.json languages keys)
EXTENSION_MAP: dict[str, str] = {
    ".py":   "python",
    ".java": "java",
    ".cs":   "csharp",
    ".js":   "javascript",
    ".jsx":  "javascript",
    ".mjs":  "javascript",
    ".cjs":  "javascript",
}

# Map our language keys to LangChain Language enum
LC_LANGUAGE_MAP: dict[str, Language] = {
    "python":     Language.PYTHON,
    "java":       Language.JAVA,
    "csharp":     Language.CSHARP,
    "javascript": Language.JS,
}

# Display icons per language
LANGUAGE_ICONS: dict[str, str] = {
    "python":     "🐍",
    "java":       "☕",
    "csharp":     "⚡",
    "javascript": "📜",
}


def detect_language(file_name: str) -> str:
    """Return the language key for a given filename, defaulting to 'python'."""
    ext = Path(file_name).suffix.lower()
    return EXTENSION_MAP.get(ext, "python")


def parse_code(file_name: str, source_code: str) -> List[Document]:
    """
    Split source_code into LangChain Documents using language-aware separators.

    Args:
        file_name: Original filename (used for metadata and language detection).
        source_code: Raw source code string.

    Returns:
        List of Document chunks ready to upsert into ChromaDB.
    """
    language = detect_language(file_name)
    lc_lang = LC_LANGUAGE_MAP.get(language, Language.PYTHON)

    splitter = RecursiveCharacterTextSplitter.from_language(
        language=lc_lang,
        chunk_size=1000,
        chunk_overlap=150,
    )

    chunks = splitter.split_text(source_code)

    return [
        Document(
            page_content=chunk,
            metadata={
                "source":      file_name,
                "language":    language,
                "chunk_index": i,
            },
        )
        for i, chunk in enumerate(chunks)
    ]
