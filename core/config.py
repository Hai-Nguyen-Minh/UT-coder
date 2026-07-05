import json
from functools import lru_cache
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent.parent / "config.json"


@lru_cache(maxsize=1)
def get_config() -> dict:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)