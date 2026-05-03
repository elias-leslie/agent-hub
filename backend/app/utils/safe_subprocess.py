"""Safer async subprocess helpers for ASGI paths."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path


def _require_executable(name: str, fallback: str) -> str:
    resolved = shutil.which(name)
    if resolved:
        return resolved
    return fallback


async def create_bash_process(
    command: str,
    *,
    working_dir: Path,
    env: dict[str, str],
) -> asyncio.subprocess.Process:
    """Start a bash command through absolute exec argv, not shell spawning."""
    env_executable = _require_executable("env", "/usr/bin/env")
    bash_executable = _require_executable("bash", "/bin/bash")
    return await asyncio.create_subprocess_exec(
        env_executable,
        "-C",
        str(working_dir),
        bash_executable,
        "-lc",
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        close_fds=False,
    )
