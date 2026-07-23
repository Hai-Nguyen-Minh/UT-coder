import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import core.config as config_module


class ConfigTests(unittest.TestCase):
    def tearDown(self):
        config_module.clear_config_cache()

    def _write_config(self, directory: str) -> Path:
        path = Path(directory) / "config.json"
        path.write_text(
            json.dumps(
                {
                    "llm": {
                        "base_url": "http://default:11434",
                        "model": "default-model",
                        "temperature": 0.1,
                    },
                    "vectorstore": {
                        "chroma_dir": "./chroma_db",
                        "embedding_model": "nomic-embed-text",
                    },
                    "server": {"host": "0.0.0.0", "port": 7860},
                    "api": {
                        "host": "127.0.0.1",
                        "port": 8000,
                        "token": "",
                        "max_request_bytes": 2097152,
                    },
                    "languages": {"python": {"test_framework": "pytest"}},
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_environment_overrides_single_config_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_config(directory)
            with patch.object(config_module, "_CONFIG_PATH", path), patch.dict(
                "os.environ",
                {
                    "UTCODER_OLLAMA_BASE_URL": "http://ollama:11434",
                    "UTCODER_LLM_MODEL": "llama3.1:8b",
                    "UTCODER_LLM_TEMPERATURE": "0.2",
                    "UTCODER_SERVER_PORT": "9000",
                    "UTCODER_API_HOST": "0.0.0.0",
                    "UTCODER_API_PORT": "8100",
                    "UTCODER_API_TOKEN": "test-token",
                },
                clear=False,
            ):
                config_module.clear_config_cache()
                config = config_module.get_config()

            self.assertEqual(config["llm"]["base_url"], "http://ollama:11434")
            self.assertEqual(config["llm"]["model"], "llama3.1:8b")
            self.assertEqual(config["llm"]["temperature"], 0.2)
            self.assertEqual(config["server"]["port"], 9000)
            self.assertEqual(config["api"]["host"], "0.0.0.0")
            self.assertEqual(config["api"]["port"], 8100)
            self.assertEqual(config["api"]["token"], "test-token")
            self.assertEqual(list(config["languages"]), ["python"])

    def test_invalid_numeric_override_fails_early(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_config(directory)
            with patch.object(config_module, "_CONFIG_PATH", path), patch.dict(
                "os.environ",
                {"UTCODER_LLM_TEMPERATURE": "khong-phai-so"},
                clear=False,
            ):
                config_module.clear_config_cache()
                with self.assertRaisesRegex(ValueError, "UTCODER_LLM_TEMPERATURE"):
                    config_module.get_config()
