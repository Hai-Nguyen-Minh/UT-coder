"""Ollama model lifecycle helpers for sequential benchmarks."""

from __future__ import annotations

import gc
import time
from typing import Any

import requests


class OllamaUnloadError(RuntimeError):
    """Ollama did not confirm that a requested model left memory."""


def _loaded_model_names(payload: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for item in payload.get("models", []):
        if not isinstance(item, dict):
            continue
        for key in ("name", "model"):
            value = item.get(key)
            if isinstance(value, str) and value:
                names.add(value)
    return names


def unload_ollama_model(
    model_id: str,
    base_url: str,
    *,
    wait_timeout: float = 45.0,
    poll_interval: float = 0.5,
    http_client=requests,
) -> None:
    """Unload a model and wait until Ollama `/api/ps` confirms release."""
    api_root = base_url.rstrip("/")
    response = http_client.post(
        f"{api_root}/api/generate",
        json={"model": model_id, "keep_alive": 0},
        timeout=15,
    )
    response.raise_for_status()

    deadline = time.monotonic() + max(0.0, wait_timeout)
    while True:
        status = http_client.get(f"{api_root}/api/ps", timeout=10)
        status.raise_for_status()
        if model_id not in _loaded_model_names(status.json()):
            gc.collect()
            return
        if time.monotonic() >= deadline:
            raise OllamaUnloadError(
                f"Model {model_id!r} is still listed by Ollama after "
                f"{wait_timeout:.1f}s"
            )
        time.sleep(max(0.05, poll_interval))
