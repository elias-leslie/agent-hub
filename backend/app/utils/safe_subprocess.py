"""Safer async subprocess helpers for ASGI paths."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def _require_executable(name: str, fallback: str) -> str:
    resolved = shutil.which(name)
    if resolved:
        return resolved
    return fallback


def _env_command(command: Sequence[str], *, working_dir: Path | None = None) -> list[str]:
    env_executable = _require_executable("env", "/usr/bin/env")
    args = [env_executable]
    if working_dir is not None:
        args.extend(["-C", str(working_dir)])
    args.extend(str(part) for part in command)
    return args


def run_process(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    close_fds: bool = False,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess through the shared safe launcher."""
    return subprocess.run(
        _env_command(command, working_dir=cwd),
        close_fds=close_fds,
        **kwargs,
    )


async def create_process(
    *command: str,
    working_dir: Path | None = None,
    stdin: int | None = None,
    env: dict[str, str] | None = None,
) -> asyncio.subprocess.Process:
    """Start a subprocess with an absolute launcher and close_fds=False."""
    return await asyncio.create_subprocess_exec(
        *_env_command(command, working_dir=working_dir),
        stdin=stdin,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        close_fds=False,
    )


async def create_bash_process(
    command: str,
    *,
    working_dir: Path,
    env: dict[str, str],
) -> asyncio.subprocess.Process:
    """Start a bash command through absolute exec argv, not shell spawning."""
    bash_executable = _require_executable("bash", "/bin/bash")
    return await asyncio.create_subprocess_exec(
        *_env_command((bash_executable, "-lc", command), working_dir=working_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        close_fds=False,
    )
