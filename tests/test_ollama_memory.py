import unittest

from core.ollama_memory import OllamaUnloadError, unload_ollama_model


class FakeResponse:
    def __init__(self, payload=None):
        self.payload = payload or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeHttpClient:
    def __init__(self, loaded_models):
        self.loaded_models = loaded_models
        self.posts = []
        self.gets = []

    def post(self, url, json, timeout):
        self.posts.append((url, json, timeout))
        return FakeResponse()

    def get(self, url, timeout):
        self.gets.append((url, timeout))
        return FakeResponse({"models": self.loaded_models})


class OllamaMemoryTests(unittest.TestCase):
    def test_unload_uses_configured_url_and_confirms_model_is_absent(self):
        client = FakeHttpClient(loaded_models=[])

        unload_ollama_model(
            "qwen2.5-coder:7b",
            "http://localhost:11434/",
            wait_timeout=0,
            http_client=client,
        )

        self.assertEqual(
            client.posts[0][0], "http://localhost:11434/api/generate"
        )
        self.assertEqual(
            client.posts[0][1],
            {"model": "qwen2.5-coder:7b", "keep_alive": 0},
        )
        self.assertEqual(client.gets[0][0], "http://localhost:11434/api/ps")

    def test_unload_fails_if_model_is_still_in_memory(self):
        client = FakeHttpClient(
            loaded_models=[{"name": "llama3.1:8b", "model": "llama3.1:8b"}]
        )

        with self.assertRaises(OllamaUnloadError):
            unload_ollama_model(
                "llama3.1:8b",
                "http://localhost:11434",
                wait_timeout=0,
                http_client=client,
            )
