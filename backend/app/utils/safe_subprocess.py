"""Safer async subprocess helpers for ASGI paths."""

from __future__ import annotations

import asyncio
import ctypes
import os
import shutil
import signal
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

_PR_SET_PDEATHSIG = 1  # linux/prctl.h


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


def _libc_prctl() -> Callable[..., int] | None:
    if not sys.platform.startswith("linux"):
        return None
    try:
        return ctypes.CDLL(None, use_errno=True).prctl
    except (OSError, AttributeError):
        return None


_PRCTL = _libc_prctl()  # loaded here so the child's preexec step only makes the call


def die_with_parent_preexec(parent_pid: int) -> Callable[[], None] | None:
    """A ``preexec_fn`` that makes the child SIGKILL itself when its parent thread dies (Linux), else None.

    Runs after ``setsid`` when ``start_new_session`` is set and survives ``exec``, so a ``/usr/bin/env`` launcher
    that execs the real program keeps it. It covers only the direct child; the rest of its process group is
    stopped by whoever recorded the group.
    """

    prctl = _PRCTL
    if prctl is None:
        return None

    def preexec() -> None:
        prctl(_PR_SET_PDEATHSIG, int(signal.SIGKILL), 0, 0, 0)
        if os.getppid() != parent_pid:  # the parent died between fork and prctl
            os._exit(1)

    return preexec


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
    stdout: int | None = asyncio.subprocess.PIPE,
    stderr: int | None = asyncio.subprocess.PIPE,
    env: dict[str, str] | None = None,
    limit: int | None = None,
    die_with_parent: bool = False,
) -> asyncio.subprocess.Process:
    """Start a subprocess with an absolute launcher and close_fds=False.

    ``die_with_parent`` asks the kernel to SIGKILL the child if this process dies (Linux only; ignored elsewhere).
    """
    kwargs: dict[str, Any] = {
        "stdin": stdin,
        "stdout": stdout,
        "stderr": stderr,
        "env": env,
        "close_fds": False,
        "start_new_session": True,
    }
    if limit is not None:
        kwargs["limit"] = limit
    if die_with_parent and (preexec := die_with_parent_preexec(os.getpid())) is not None:
        kwargs["preexec_fn"] = preexec
    return await asyncio.create_subprocess_exec(
        *_env_command(command, working_dir=working_dir),
        **kwargs,
    )


def bash_argv(command: str) -> tuple[str, str, str]:
    """The absolute-path bash invocation for ``command`` (a login shell running one command string)."""
    return (_require_executable("bash", "/bin/bash"), "-lc", command)


async def create_bash_process(
    command: str,
    *,
    working_dir: Path,
    env: dict[str, str],
) -> asyncio.subprocess.Process:
    """Start a bash command through absolute exec argv, not shell spawning."""
    return await asyncio.create_subprocess_exec(
        *_env_command(bash_argv(command), working_dir=working_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        close_fds=False,
        start_new_session=True,
    )
