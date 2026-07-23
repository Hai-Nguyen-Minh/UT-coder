"""Tạo gói triển khai tối giản cho máy chủ Ubuntu."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TARGET_ZIP = ROOT / "utcoder_server.zip"
INCLUDE_DIRS = ("core", "ui", "chroma_db")
INCLUDE_FILES = (
    "main.py",
    "server.py",
    "config.json",
    ".env.example",
    ".dockerignore",
    "docker-compose.server.yml",
    "Dockerfile",
    "requirements.txt",
    "pytest.ini",
    "uninstall.sh",
    "core/dataset/valid_dataset.json",
)
EXCLUDED_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".git",
    "CodeRM_UnitTest",
    "CodeRM_UnitTest (test)",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log", ".csv", ".jsonl", ".md"}
GENERATED_BENCHMARK_PREFIXES = (
    "benchmark_results",
    "benchmark_progress",
    "benchmark_status",
    "benchmark_summary",
    "benchmark_paired_comparison",
    "validity_stability",
    "quality_score_distribution",
    "quality_components",
)


def _should_include(path: Path) -> bool:
    if path.suffix in EXCLUDED_SUFFIXES:
        return False
    if path.parent.name == "benchmark" and path.name.startswith(
        GENERATED_BENCHMARK_PREFIXES
    ):
        return False
    if path.suffix == ".json" and path.parent.name == "dataset":
        return False
    return True


def create_server_zip(target_zip: Path = TARGET_ZIP) -> Path:
    """Đóng gói runtime server; docker-compose.server.yml được đổi tên trong ZIP."""
    target_zip = Path(target_zip).resolve()
    print(f"Creating {target_zip.name}...")

    with zipfile.ZipFile(target_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for directory_name in INCLUDE_DIRS:
            directory = ROOT / directory_name
            if not directory.exists():
                continue
            for current_root, directories, files in os.walk(directory):
                directories[:] = [
                    name
                    for name in directories
                    if name not in EXCLUDED_DIR_NAMES and not name.endswith("_artifacts")
                ]
                for filename in files:
                    file_path = Path(current_root) / filename
                    if _should_include(file_path):
                        archive.write(file_path, file_path.relative_to(ROOT).as_posix())

        for relative_name in INCLUDE_FILES:
            file_path = ROOT / relative_name
            if not file_path.exists():
                continue
            archive_name = (
                "docker-compose.yml"
                if relative_name == "docker-compose.server.yml"
                else Path(relative_name).as_posix()
            )
            archive.write(file_path, archive_name)

    print(f"Server package created: {target_zip}")
    return target_zip


if __name__ == "__main__":
    create_server_zip()
