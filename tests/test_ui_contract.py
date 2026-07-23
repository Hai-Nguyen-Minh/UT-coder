import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def _load_ui_module():
    gradio = types.ModuleType("gradio")
    gradio.update = lambda **kwargs: kwargs

    parser = types.ModuleType("core.code_parser")
    parser.LANGUAGE_ICONS = {"python": "🐍"}
    parser.detect_language = lambda _name: "python"

    config = types.ModuleType("core.config")
    config.get_config = lambda: {
        "languages": {"python": {"display": "Python", "test_framework": "pytest"}},
        "vectorstore": {
            "chroma_dir": "./chroma_db",
            "embedding_model": "nomic-embed-text",
        },
    }

    llm = types.ModuleType("core.llm")
    llm.get_model_name = lambda: "qwen2.5-coder:7b"

    module_name = "utcoder_ui_contract_test"
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "ui" / "app.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules,
        {
            "gradio": gradio,
            "core.code_parser": parser,
            "core.config": config,
            "core.llm": llm,
        },
    ):
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


class UIContractTests(unittest.TestCase):
    def test_upload_and_clear_callbacks_match_gradio_output_counts(self):
        app = _load_ui_module()
        self.assertEqual(len(app.on_file_upload(None)), 5)
        self.assertEqual(len(app.on_clear()), 10)

        with tempfile.TemporaryDirectory() as directory:
            python_file = Path(directory) / "calculator.py"
            python_file.write_text("def add(a, b): return a + b", encoding="utf-8")
            uploaded = types.SimpleNamespace(name=str(python_file))
            self.assertEqual(len(app.on_file_upload(uploaded)), 5)

    def test_low_coverage_candidate_is_not_downloadable(self):
        app = _load_ui_module()
        generator = types.ModuleType("core.generator")

        def fake_reflection(*_args, **_kwargs):
            yield "coverage below target", "def test_weak():\n    assert True\n", {
                "success": True,
                "meets_coverage": False,
                "coverage": 40.0,
                "missing_lines": [2],
            }

        generator.generate_with_reflection = fake_reflection
        with tempfile.TemporaryDirectory() as directory:
            python_file = Path(directory) / "calculator.py"
            python_file.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            uploaded = types.SimpleNamespace(name=str(python_file))
            with patch.dict(sys.modules, {"core.generator": generator}):
                updates = list(app.on_generate(uploaded))

        final_update = updates[-1]
        self.assertIn("Không tạo file tải xuống", final_update[1])
        self.assertEqual(final_update[2], "")
        self.assertFalse(final_update[3]["visible"])


if __name__ == "__main__":
    unittest.main()
