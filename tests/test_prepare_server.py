from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import prepare_server


class PrepareServerTests(unittest.TestCase):
    def test_package_uses_one_config_and_renames_server_compose(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "core").mkdir()
            (root / "ui").mkdir()
            (root / "chroma_db").mkdir()
            (root / "core" / "runtime.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "core" / "README.md").write_text("runtime docs", encoding="utf-8")
            (root / "core" / "benchmark").mkdir()
            (root / "core" / "benchmark" / "BENCHMARK.md").write_text(
                "benchmark docs", encoding="utf-8"
            )
            (root / "core" / "benchmark" / "benchmark_status.txt").write_text("run")
            (root / "core" / "dataset").mkdir()
            (root / "core" / "dataset" / "valid_dataset.json").write_text("[]")
            (root / "config.json").write_text("{}", encoding="utf-8")
            (root / "docker-compose.server.yml").write_text("services: {}")
            target = root / "server.zip"

            with patch.object(prepare_server, "ROOT", root), patch.object(
                prepare_server,
                "INCLUDE_FILES",
                (
                    "config.json",
                    "docker-compose.server.yml",
                    "core/dataset/valid_dataset.json",
                ),
            ):
                prepare_server.create_server_zip(target)

            with zipfile.ZipFile(target) as archive:
                names = set(archive.namelist())

            self.assertIn("config.json", names)
            self.assertIn("docker-compose.yml", names)
            self.assertIn("core/runtime.py", names)
            self.assertNotIn("docker-compose.server.yml", names)
            self.assertIn("core/dataset/valid_dataset.json", names)
            self.assertNotIn("config.server.json", names)
            self.assertNotIn("config.local.json", names)
            self.assertNotIn("core/benchmark/benchmark_status.txt", names)
            self.assertNotIn("core/README.md", names)
            self.assertNotIn("core/benchmark/BENCHMARK.md", names)
            self.assertFalse(any(name.lower().endswith(".md") for name in names))
