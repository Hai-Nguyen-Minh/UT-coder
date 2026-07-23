"""REST API cho UTcoder và VS Code extension.

API hiện hỗ trợ chính thức Python. Sinh test luôn đi qua cùng pipeline
RAG -> Ollama -> sandbox -> self-reflection như giao diện Gradio.
"""

from __future__ import annotations

import hmac
import importlib.util
import json
import logging
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

sys.path.insert(0, str(Path(__file__).parent))

from core.benchmark.metrics import DEFAULT_MINIMUM_COVERAGE
from core.config import get_config
from core.sandbox.base import SandboxInfrastructureError


API_VERSION = "0.3.0"
PROJECT_ROOT = Path(__file__).resolve().parent
_GENERATION_LOCK = threading.Lock()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("utcoder.api")


class APIRequestError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _api_config() -> dict:
    return get_config().get("api", {})


def generate_tests_with_reflection(**kwargs):
    """Lazy-load pipeline AI để health/API vẫn khởi động và báo lỗi rõ ràng."""
    from core.generator import generate_with_reflection

    return generate_with_reflection(**kwargs)


def run_compile_check(source_code: str, test_code: str, file_name: str) -> dict:
    from core.compiler import compile_check

    return compile_check(source_code, test_code, file_name)


def run_coverage_analysis(source_code: str, test_code: str, file_name: str) -> dict:
    from core.coverager import analyse_coverage

    return analyse_coverage(source_code, test_code, file_name)


def _resolve_chroma_dir(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _ollama_health() -> dict:
    cfg = get_config()
    llm_cfg = cfg.get("llm", {})
    base_url = str(llm_cfg.get("base_url", "http://localhost:11434")).rstrip("/")
    configured_model = str(llm_cfg.get("model", ""))
    embedding_model = str(
        cfg.get("vectorstore", {}).get("embedding_model", "nomic-embed-text")
    )
    try:
        response = requests.get(f"{base_url}/api/tags", timeout=3.0)
        response.raise_for_status()
        payload = response.json()
        models = {
            str(item.get("name") or item.get("model") or "")
            for item in payload.get("models", [])
            if isinstance(item, dict)
        }
        def is_installed(model: str) -> bool:
            return model in models or (":" not in model and f"{model}:latest" in models)

        model_ready = is_installed(configured_model)
        embedding_ready = is_installed(embedding_model)
        ready = model_ready and embedding_ready
        missing = [
            name
            for name, available in (
                (configured_model, model_ready),
                (embedding_model, embedding_ready),
            )
            if not available
        ]
        return {
            "ready": ready,
            "model": configured_model,
            "embedding_model": embedding_model,
            "message": (
                "Ollama connected; generation and embedding models are available."
                if ready
                else "Ollama connected but these models are missing: "
                + ", ".join(repr(name) for name in missing)
            ),
        }
    except (requests.RequestException, ValueError, TypeError) as exc:
        return {
            "ready": False,
            "model": configured_model,
            "embedding_model": embedding_model,
            "message": f"Ollama unavailable: {exc}",
        }


def get_health_status(*, deep: bool = False) -> dict:
    """Kiểm tra Ollama thật, Chroma path và Python sandbox dependencies."""
    cfg = get_config()
    chroma_dir = _resolve_chroma_dir(
        str(cfg.get("vectorstore", {}).get("chroma_dir", "./chroma_db"))
    )
    chroma_ready = chroma_dir.is_dir() or (
        chroma_dir.parent.is_dir() and os.access(chroma_dir.parent, os.W_OK)
    )
    missing_modules = [
        name
        for name in ("pytest", "pytest_cov", "coverage")
        if importlib.util.find_spec(name) is None
    ]
    sandbox = {
        "ready": not missing_modules,
        "message": (
            "Python sandbox dependencies are installed."
            if not missing_modules
            else "Missing Python sandbox modules: " + ", ".join(missing_modules)
        ),
    }
    if deep and sandbox["ready"]:
        try:
            from core.sandbox.preflight import run_sandbox_preflight

            result = run_sandbox_preflight()
            sandbox["coverage"] = result.coverage
            sandbox["message"] = "Deterministic sandbox preflight passed."
        except Exception as exc:
            sandbox = {"ready": False, "message": f"Sandbox preflight failed: {exc}"}

    components = {
        "ollama": _ollama_health(),
        "chroma": {
            "ready": chroma_ready,
            "path": str(chroma_dir),
            "message": (
                "ChromaDB directory is available."
                if chroma_dir.is_dir()
                else "ChromaDB directory can be created on first use."
                if chroma_ready
                else "ChromaDB directory is not accessible."
            ),
        },
        "sandbox": sandbox,
    }
    ready = all(bool(item.get("ready")) for item in components.values())
    model = str(cfg.get("llm", {}).get("model", ""))
    return {
        "ready": ready,
        "message": (
            f"UTcoder API is ready (model: {model})."
            if ready
            else "UTcoder API is not ready; inspect component status."
        ),
        "version": API_VERSION,
        "language": "python",
        "components": components,
    }


def _clean_generated_code(code: str) -> str:
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)\n```", code, re.DOTALL)
    return (max(blocks, key=len) if blocks else code).strip()


def _validate_python_payload(body: dict, *, require_test: bool = False) -> tuple[str, str, str]:
    file_name = str(body.get("file_name", "")).strip()
    source_code = body.get("source_code", "")
    test_code = body.get("test_code", "")
    language = str(body.get("language", "python") or "python").strip().lower()

    if not file_name or not isinstance(source_code, str) or not source_code.strip():
        raise APIRequestError("'file_name' and non-empty 'source_code' are required.")
    if Path(file_name).name != file_name or Path(file_name).suffix.lower() != ".py":
        raise APIRequestError("UTcoder API currently supports Python .py files only.", 422)
    if language != "python":
        raise APIRequestError("UTcoder API currently supports language='python' only.", 422)
    if require_test and (not isinstance(test_code, str) or not test_code.strip()):
        raise APIRequestError("Non-empty 'test_code' is required.")
    return file_name, source_code, str(test_code)


class UTCoderHandler(BaseHTTPRequestHandler):
    server_version = f"UTcoderAPI/{API_VERSION}"

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        configured = str(_api_config().get("token", "") or "")
        if not configured:
            return True
        supplied = self.headers.get("Authorization", "")
        prefix = "Bearer "
        return supplied.startswith(prefix) and hmac.compare_digest(
            supplied[len(prefix):], configured
        )

    def _require_authorization(self) -> bool:
        if self._authorized():
            return True
        self._send_json({"success": False, "error": "Unauthorized."}, status=401)
        return False

    def _read_body(self) -> dict:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
        if content_type != "application/json":
            raise APIRequestError("Content-Type must be application/json.", 415)
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise APIRequestError("Invalid Content-Length header.") from exc
        maximum = int(_api_config().get("max_request_bytes", 2 * 1024 * 1024))
        if content_length <= 0:
            raise APIRequestError("JSON request body is required.")
        if content_length > maximum:
            # Đọc hết request vượt ngưỡng ở mức hữu hạn để tránh TCP RST trước
            # khi client nhận được JSON 413 (đặc biệt với HTTPServer trên Windows).
            # Với Content-Length phi lý, đóng connection thay vì chờ attacker gửi hết.
            safe_drain_limit = max(maximum * 2, maximum + 64 * 1024)
            if content_length <= safe_drain_limit:
                self.rfile.read(content_length)
            else:
                self.close_connection = True
            raise APIRequestError(
                f"Request body exceeds the {maximum}-byte limit.", status=413
            )
        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise APIRequestError("Request body is not valid UTF-8 JSON.") from exc
        if not isinstance(payload, dict):
            raise APIRequestError("JSON request body must be an object.")
        return payload

    def do_GET(self) -> None:
        if not self._require_authorization():
            return
        parsed = urlparse(self.path)
        if parsed.path != "/api/health":
            self._send_json({"success": False, "error": "Not found."}, status=404)
            return
        deep = parse_qs(parsed.query).get("deep", ["0"])[0].lower() in {
            "1", "true", "yes"
        }
        status = get_health_status(deep=deep)
        self._send_json(status, status=200 if status["ready"] else 503)

    def do_POST(self) -> None:
        if not self._require_authorization():
            return
        parsed = urlparse(self.path)
        handlers = {
            "/api/generate": self._handle_generate,
            "/api/compile-check": self._handle_compile_check,
            "/api/coverage": self._handle_coverage,
        }
        handler = handlers.get(parsed.path)
        if handler is None:
            self._send_json({"success": False, "error": "Not found."}, status=404)
            return
        try:
            body = self._read_body()
            handler(body)
        except APIRequestError as exc:
            self._send_json({"success": False, "error": str(exc)}, status=exc.status)
        except SandboxInfrastructureError as exc:
            logger.exception("Sandbox infrastructure failure")
            self._send_json({"success": False, "error": str(exc)}, status=503)
        except Exception as exc:
            logger.exception("API request failed")
            self._send_json({"success": False, "error": str(exc)}, status=500)

    def _handle_generate(self, body: dict) -> None:
        file_name, source_code, _ = _validate_python_payload(body)
        if not _GENERATION_LOCK.acquire(blocking=False):
            raise APIRequestError(
                "Another generation request is already running. Retry shortly.", 429
            )
        try:
            final_code = ""
            final_result: dict = {}
            final_status = ""
            for status, code, result in generate_tests_with_reflection(
                file_name=file_name,
                source_code=source_code,
                target_coverage=DEFAULT_MINIMUM_COVERAGE,
                max_retries=3,
            ):
                final_status = str(status or final_status)
                if isinstance(code, str) and code.strip():
                    final_code = code
                if isinstance(result, dict) and result:
                    final_result = result
        finally:
            _GENERATION_LOCK.release()

        accepted = bool(
            final_result.get("success") and final_result.get("meets_coverage")
        )
        coverage = final_result.get("coverage")
        cleaned = _clean_generated_code(final_code)
        self._send_json({
            "success": accepted,
            "accepted": accepted,
            "code": cleaned if accepted else "",
            "file_name": file_name,
            "test_file_name": f"test_{Path(file_name).stem}.py",
            "language": "python",
            "coverage": coverage,
            "missing_lines": final_result.get("missing_lines", []),
            "execution_status": final_result.get("execution_status", "unknown"),
            "status": final_status,
            "error": "" if accepted else (
                "Generated candidate did not pass pytest with at least "
                f"{DEFAULT_MINIMUM_COVERAGE:.0f}% valid coverage."
            ),
        })

    def _handle_compile_check(self, body: dict) -> None:
        file_name, source_code, test_code = _validate_python_payload(
            body, require_test=True
        )
        result = run_compile_check(source_code, test_code, file_name)
        self._send_json({"success": True, "language": "python", "result": result})

    def _handle_coverage(self, body: dict) -> None:
        file_name, source_code, test_code = _validate_python_payload(
            body, require_test=True
        )
        result = run_coverage_analysis(source_code, test_code, file_name)
        self._send_json({"success": True, "language": "python", "result": result})

    def log_message(self, format: str, *args) -> None:
        logger.info("%s - %s", self.client_address[0], format % args)


class UTCoderHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_server(host: str | None = None, port: int | None = None) -> UTCoderHTTPServer:
    cfg = _api_config()
    bind_host = str(cfg.get("host", "127.0.0.1")) if host is None else host
    bind_port = int(cfg.get("port", 8000)) if port is None else int(port)
    return UTCoderHTTPServer(
        (bind_host, bind_port),
        UTCoderHandler,
    )


def main() -> None:
    server = create_server()
    host, port = server.server_address[:2]
    logger.info("UTcoder Python API started on http://%s:%d", host, port)
    logger.info("Endpoints: GET /api/health, POST /api/generate, /api/compile-check, /api/coverage")
    if not str(_api_config().get("token", "") or ""):
        logger.warning(
            "UTCODER_API_TOKEN is empty. Keep the API on loopback/SSH tunnel; "
            "do not expose it directly to the Internet."
        )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down API...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
