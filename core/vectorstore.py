"""
core/vectorstore.py
-------------------
ChromaDB vector store management.
Uses OllamaEmbeddings with a dedicated embedding model (e.g., nomic-embed-text)
to embed code chunks and support similarity search for RAG context.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import List

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings

from core.config import get_config

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_embeddings() -> OllamaEmbeddings:
    """Return a cached OllamaEmbeddings instance using a dedicated embedding model."""
    # FIX: Don't use the primary LLM model for embeddings.
    # Check if you have an embedding model defined in config, otherwise fallback to a safe default.
    config = get_config()

    # Safely look for a dedicated embedding key, or fall back to 'nomic-embed-text'
    model = config.get("vectorstore", {}).get("embedding_model", "nomic-embed-text")

    logger.info("Initialising OllamaEmbeddings with model: %s", model)
    return OllamaEmbeddings(model=model)


def _get_persist_dir() -> str:
    return get_config()["vectorstore"]["chroma_dir"]


def index_documents(docs: List[Document], collection_name: str) -> Chroma:
    """
    Clear any existing collection with the same name and index the provided
    documents into ChromaDB.

    Args:
        docs: List of LangChain Document objects to embed and store.
        collection_name: ChromaDB collection name (one per source file).

    Returns:
        The resulting Chroma vector store instance.
    """
    persist_dir = _get_persist_dir()

    # Drop stale collection to avoid duplicate embeddings on re-uploads
    try:
        client = chromadb.PersistentClient(path=persist_dir)
        client.delete_collection(collection_name)
        logger.info("Deleted existing ChromaDB collection: %s", collection_name)
    except Exception:
        pass  # Collection didn't exist — that's fine

    logger.info(
        "Indexing %d chunks into ChromaDB collection '%s'", len(docs), collection_name
    )
    vectorstore = Chroma.from_documents(
        documents=docs,
        embedding=_get_embeddings(),
        collection_name=collection_name,
        persist_directory=persist_dir,
    )
    return vectorstore


def similarity_search(
    query: str,
    collection_name: str,
    k: int = 3,
) -> List[Document]:
    """
    Retrieve the k most similar document chunks to the query.

    Args:
        query:           Free-text query string.
        collection_name: ChromaDB collection to search.
        k:               Number of results to return.

    Returns:
        List of matching Document chunks (may be empty on error).
    """
    persist_dir = _get_persist_dir()
    try:
        vectorstore = Chroma(
            collection_name=collection_name,
            embedding_function=_get_embeddings(),
            persist_directory=persist_dir,
        )
        return vectorstore.similarity_search(query, k=k)
    except Exception as exc:
        logger.warning("ChromaDB similarity search failed: %s", exc)
        return []