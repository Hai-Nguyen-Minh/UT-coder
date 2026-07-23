"""Run an untrusted child process with bounded resources and tree cleanup."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Mapping, Sequence


def run_limited_process(
    command: Sequence[str],
    *,
    cwd: str | Path,
    env: Mapping[str, str] | None = None,
    timeout: float,
    memory_mb: int,
    cpu_seconds: int,
    file_size_mb: int = 8,
    max_files: int = 64,
    max_processes: int = 16,
    max_output_bytes: int = 2 * 1024 * 1024,
) -> subprocess.CompletedProcess[str]:
    """Execute a command with POSIX rlimits and terminate its process group."""
    effective_command = list(command)
    if os.name == "posix":
        runner = Path(__file__).with_name("resource_runner.py")
        effective_command = [
            sys.executable,
            str(runner),
            "--memory-mb", str(memory_mb),
            "--cpu-seconds", str(cpu_seconds),
            "--file-size-mb", str(file_size_mb),
            "--max-files", str(max_files),
            "--max-processes", str(max_processes),
            "--",
            *effective_command,
        ]

    def read_tail(stream) -> str:
        stream.flush()
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - max_output_bytes))
        return stream.read()

    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8", errors="replace") as stdout_file, tempfile.TemporaryFile(
        mode="w+t", encoding="utf-8", errors="replace"
    ) as stderr_file:
        process = subprocess.Popen(
            effective_command,
            cwd=str(cwd),
            env=dict(env) if env is not None else None,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            start_new_session=os.name == "posix",
        )
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            process.wait()
            exc.stdout = read_tail(stdout_file)
            exc.stderr = read_tail(stderr_file)
            raise
        stdout = read_tail(stdout_file)
        stderr = read_tail(stderr_file)

    return subprocess.CompletedProcess(
        args=effective_command,
        returncode=process.returncode,
        stdout=stdout,
        stderr=stderr,
    )
