import threading
import unittest
from unittest.mock import Mock, patch

import requests

import server as api_server


class ServerAPITests(unittest.TestCase):
    def setUp(self):
        self.config_patch = patch.object(
            api_server,
            "_api_config",
            return_value={
                "host": "127.0.0.1",
                "port": 0,
                "token": "secret-token",
                "max_request_bytes": 4096,
            },
        )
        self.config_patch.start()
        self.httpd = api_server.create_server("127.0.0.1", 0)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.httpd.server_address[:2]
        self.base_url = f"http://{host}:{port}"
        self.headers = {
            "Authorization": "Bearer secret-token",
            "Content-Type": "application/json",
        }

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        self.config_patch.stop()

    def test_health_requires_token_and_returns_component_status(self):
        unauthorized = requests.get(f"{self.base_url}/api/health", timeout=2)
        self.assertEqual(unauthorized.status_code, 401)

        health = {
            "ready": True,
            "message": "ready",
            "version": api_server.API_VERSION,
            "language": "python",
            "components": {},
        }
        with patch.object(api_server, "get_health_status", return_value=health):
            response = requests.get(
                f"{self.base_url}/api/health",
                headers={"Authorization": "Bearer secret-token"},
                timeout=2,
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ready"])
        self.assertEqual(response.json()["language"], "python")

    def test_ollama_health_requires_generation_and_embedding_models(self):
        ollama_response = Mock()
        ollama_response.raise_for_status.return_value = None
        ollama_response.json.return_value = {
            "models": [
                {"name": "qwen2.5-coder:7b"},
                {"name": "nomic-embed-text:latest"},
            ]
        }
        config = {
            "llm": {
                "base_url": "http://localhost:11434",
                "model": "qwen2.5-coder:7b",
            },
            "vectorstore": {"embedding_model": "nomic-embed-text"},
        }
        with patch.object(api_server, "get_config", return_value=config), patch.object(
            api_server.requests,
            "get",
            return_value=ollama_response,
        ):
            status = api_server._ollama_health()

        self.assertTrue(status["ready"])
        self.assertEqual(status["embedding_model"], "nomic-embed-text")

    def test_generate_uses_reflection_and_returns_only_accepted_python(self):
        generated = "import pytest\nfrom calculator import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"

        def fake_reflection(**kwargs):
            self.assertEqual(kwargs["file_name"], "calculator.py")
            self.assertEqual(kwargs["target_coverage"], 80.0)
            yield "running", generated, {}
            yield "accepted", generated, {
                "success": True,
                "meets_coverage": True,
                "coverage": 100.0,
                "missing_lines": [],
                "execution_status": "tests_passed",
            }

        with patch.object(
            api_server, "generate_tests_with_reflection", side_effect=fake_reflection
        ) as mocked:
            response = requests.post(
                f"{self.base_url}/api/generate",
                headers=self.headers,
                json={
                    "file_name": "calculator.py",
                    "source_code": "def add(a, b): return a + b",
                    "language": "python",
                },
                timeout=2,
            )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertTrue(payload["accepted"])
        self.assertEqual(payload["coverage"], 100.0)
        self.assertEqual(payload["test_file_name"], "test_calculator.py")
        self.assertEqual(payload["code"], generated.strip())
        mocked.assert_called_once()

    def test_generate_rejects_non_python_before_calling_model(self):
        with patch.object(api_server, "generate_tests_with_reflection") as mocked:
            response = requests.post(
                f"{self.base_url}/api/generate",
                headers=self.headers,
                json={
                    "file_name": "Calculator.java",
                    "source_code": "class Calculator {}",
                    "language": "java",
                },
                timeout=2,
            )

        self.assertEqual(response.status_code, 422)
        self.assertFalse(response.json()["success"])
        mocked.assert_not_called()

    def test_generate_does_not_return_unaccepted_candidate(self):
        def fake_reflection(**_kwargs):
            yield "coverage below target", "def test_weak():\n    assert True\n", {
                "success": True,
                "meets_coverage": False,
                "coverage": 40.0,
                "execution_status": "tests_passed",
            }

        with patch.object(
            api_server,
            "generate_tests_with_reflection",
            side_effect=fake_reflection,
        ):
            response = requests.post(
                f"{self.base_url}/api/generate",
                headers=self.headers,
                json={
                    "file_name": "calculator.py",
                    "source_code": "def add(a, b): return a + b",
                    "language": "python",
                },
                timeout=2,
            )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(payload["success"])
        self.assertFalse(payload["accepted"])
        self.assertEqual(payload["coverage"], 40.0)
        self.assertEqual(payload["code"], "")

    def test_compile_and_coverage_endpoints_use_python_sandbox_adapters(self):
        body = {
            "file_name": "calculator.py",
            "source_code": "def add(a, b): return a + b",
            "test_code": "def test_add(): assert True",
            "language": "python",
        }
        with patch.object(
            api_server,
            "run_compile_check",
            return_value={"has_issues": False},
        ) as compile_mock:
            compile_response = requests.post(
                f"{self.base_url}/api/compile-check",
                headers=self.headers,
                json=body,
                timeout=2,
            )
        with patch.object(
            api_server,
            "run_coverage_analysis",
            return_value={"coverage_pct": 100.0},
        ) as coverage_mock:
            coverage_response = requests.post(
                f"{self.base_url}/api/coverage",
                headers=self.headers,
                json=body,
                timeout=2,
            )

        self.assertEqual(compile_response.status_code, 200)
        self.assertFalse(compile_response.json()["result"]["has_issues"])
        self.assertEqual(coverage_response.status_code, 200)
        self.assertEqual(coverage_response.json()["result"]["coverage_pct"], 100.0)
        compile_mock.assert_called_once()
        coverage_mock.assert_called_once()

    def test_invalid_json_and_large_request_are_rejected(self):
        invalid = requests.post(
            f"{self.base_url}/api/generate",
            headers=self.headers,
            data="{not-json",
            timeout=2,
        )
        self.assertEqual(invalid.status_code, 400)

        large = requests.post(
            f"{self.base_url}/api/generate",
            headers=self.headers,
            data="x" * 5000,
            timeout=2,
        )
        self.assertEqual(large.status_code, 413)
