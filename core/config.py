import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

_CONFIG_PATH = Path(__file__).parent.parent / "config.json"


def _read_env(name: str, converter: Callable[[str], Any] = str) -> Any | None:
    """Đọc biến môi trường và báo lỗi cấu hình ngay khi giá trị không hợp lệ."""
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return None
    try:
        return converter(raw_value.strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Biến môi trường {name} có giá trị không hợp lệ: {raw_value!r}") from exc


def _apply_environment_overrides(config: dict) -> dict:
    """Giữ một config.json duy nhất, còn khác biệt môi trường đi qua ENV."""
    overrides = (
        ("UTCODER_OLLAMA_BASE_URL", ("llm", "base_url"), str),
        ("UTCODER_LLM_MODEL", ("llm", "model"), str),
        ("UTCODER_LLM_TEMPERATURE", ("llm", "temperature"), float),
        ("UTCODER_CHROMA_DIR", ("vectorstore", "chroma_dir"), str),
        ("UTCODER_EMBEDDING_MODEL", ("vectorstore", "embedding_model"), str),
        ("UTCODER_SERVER_HOST", ("server", "host"), str),
        ("UTCODER_SERVER_PORT", ("server", "port"), int),
        ("UTCODER_API_HOST", ("api", "host"), str),
        ("UTCODER_API_PORT", ("api", "port"), int),
        ("UTCODER_API_TOKEN", ("api", "token"), str),
        ("UTCODER_API_MAX_REQUEST_BYTES", ("api", "max_request_bytes"), int),
    )
    for env_name, (section, key), converter in overrides:
        value = _read_env(env_name, converter)
        if value is not None:
            config[section][key] = value
    return config


@lru_cache(maxsize=1)
def get_config() -> dict:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return _apply_environment_overrides(json.load(f))


def clear_config_cache() -> None:
    """Hữu ích cho test hoặc tiến trình cần nạp lại biến môi trường."""
    get_config.cache_clear()
