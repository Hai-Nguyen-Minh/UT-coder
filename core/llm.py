"""
core/llm.py
-----------
LangChain ChatOllama wrapper.
Reads model & temperature from config.json and returns a cached LLM instance.
"""

from functools import lru_cache
from langchain_ollama import ChatOllama
from core.config import get_config

@lru_cache(maxsize=1)
def get_llm() -> ChatOllama:
    """Return a cached ChatOllama instance configured from config.json."""
    cfg = get_config()["llm"]
    return ChatOllama(
        base_url=cfg.get("base_url", "http://ollama:11434"),
        model=cfg["model"],
        temperature=cfg.get("temperature", 0.3),
    )


def get_model_name() -> str:
    """Return the configured model name string."""
    return get_config()["llm"]["model"]
