"""POSIX exec wrapper that applies hard resource limits before untrusted code."""

from __future__ import annotations

import argparse
import os
import sys


DEFAULT_SANDBOX_USER = "utcoder-sandbox"


def _apply_limit(resource_module, limit_name: str, value: int) -> None:
    limit = getattr(resource_module, limit_name, None)
    if limit is None:
        return
    try:
        resource_module.setrlimit(limit, (value, value))
    except (OSError, ValueError):
        # Some container kernels do not expose every limit. The caller still
        # retains wall-clock timeout and all other supported limits.
        pass


def _configure_posix_sandbox(resource_module, pwd_module, os_module, options) -> bool:
    """Apply limits and enter the dedicated Linux sandbox identity.

    RLIMIT_NPROC is deliberately enabled only for the dedicated UID. Linux
    accounts processes per real UID, which made the old global `nobody` user
    intermittently reject exec() with EAGAIN on Ubuntu hosts.

    Returns True when the process limit was safely enabled. A root process
    fails closed if the Docker image was not rebuilt with the sandbox account.
    """
    _apply_limit(resource_module, "RLIMIT_CORE", 0)
    _apply_limit(resource_module, "RLIMIT_AS", options.memory_mb * 1024 * 1024)
    _apply_limit(resource_module, "RLIMIT_CPU", options.cpu_seconds)
    _apply_limit(resource_module, "RLIMIT_FSIZE", options.file_size_mb * 1024 * 1024)
    _apply_limit(resource_module, "RLIMIT_NOFILE", options.max_files)

    sandbox_user = os_module.environ.get(
        "UTCODER_SANDBOX_USER", DEFAULT_SANDBOX_USER
    )
    try:
        identity = pwd_module.getpwnam(sandbox_user)
    except KeyError:
        if os_module.geteuid() == 0:
            raise RuntimeError(
                "Sandbox setup failed: required Linux user "
                f"'{sandbox_user}' does not exist. Rebuild the Docker image."
            )
        # A non-root development process cannot switch users. It still keeps
        # the memory/CPU/file limits, but avoids RLIMIT_NPROC on a shared UID.
        return False

    current_uid = os_module.geteuid()
    if current_uid == 0:
        os_module.setgroups([])
        os_module.setgid(identity.pw_gid)
        os_module.setuid(identity.pw_uid)
    elif current_uid != identity.pw_uid:
        # Running unprivileged outside the container is already safer than
        # root, but its UID may be shared, so NPROC must not be applied.
        return False

    _apply_limit(resource_module, "RLIMIT_NPROC", options.max_processes)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--memory-mb", type=int, required=True)
    parser.add_argument("--cpu-seconds", type=int, required=True)
    parser.add_argument("--file-size-mb", type=int, default=8)
    parser.add_argument("--max-files", type=int, default=64)
    parser.add_argument("--max-processes", type=int, default=16)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    options = parser.parse_args()
    command = options.command[1:] if options.command[:1] == ["--"] else options.command
    if not command:
        return 2

    if os.name == "posix":
        import pwd
        import resource

        _configure_posix_sandbox(resource, pwd, os, options)

    os.execvpe(command[0], command, os.environ.copy())
    return 127


if __name__ == "__main__":
    sys.exit(main())
