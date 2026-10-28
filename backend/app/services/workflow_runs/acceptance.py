"""Acceptance commands: the runner, not the agent, decides a step is done.

After the executor finishes, the engine runs each of the step's commands in its worktree. Every command's exit code,
duration and a trimmed output tail are recorded on the attempt; any non-zero exit sends the step back for another
attempt with that output in the next packet (``failure_note``).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .executor_common import child_env, load_defaults
from .processes import start_tracked, wait_exit

logger = logging.getLogger(__name__)


def commands_of(definition: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The step's acceptance commands as ``{cmd, timeout_s}``; stored runs may hold bare strings."""

    out: list[dict[str, Any]] = []
    for item in definition.get("acceptance") or []:
        if isinstance(item, str):
            out.append({"cmd": item, "timeout_s": None})
        else:
            out.append({"cmd": item["cmd"], "timeout_s": item.get("timeout_s")})
    return out


async def _run_one(cmd: str, worktree: Path, timeout: float | None, tail_chars: int, drain_seconds: float) -> dict[str, Any]:
    started = time.monotonic()
    tail = bytearray()
    timed_out = False
    tracked = await start_tracked(
        "bash",
        "-c",
        cmd,
        kind="acceptance",
        working_dir=worktree,
        stdin=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.STDOUT,
        env=child_env(load_defaults()),
    )
    process = tracked.process

    async def drain() -> None:
        stream = process.stdout
        while stream is not None and (chunk := await stream.read(8192)):
            tail.extend(chunk)
            del tail[: -tail_chars * 4]

    reader = asyncio.create_task(drain())
    try:
        # The command's own exit decides pass or fail: a grandchild that keeps the pipe open is not the command.
        timed_out = not await wait_exit(process, timeout)
    finally:
        # The command and everything it started, whether it timed out, was cancelled or exited and left children.
        await tracked.kill()
        await asyncio.wait({reader}, timeout=drain_seconds)
        reader.cancel()
    if timed_out:  # the only way a command is cut short: the caller's own limit, so it is logged and recorded
        logger.warning("acceptance command %r was stopped at its own timeout_s of %ss", cmd, timeout)
    text = tail.decode(errors="replace").strip()
    return {
        "cmd": cmd,
        "exit_code": None if timed_out else process.returncode,
        "timed_out": timed_out,
        "duration_s": round(time.monotonic() - started, 2),
        "output_tail": text[-tail_chars:],
    }


async def run_acceptance(
    commands: Sequence[Mapping[str, Any]],
    worktree: Path,
    *,
    tail_chars: int,
    drain_seconds: float,
) -> list[dict[str, Any]]:
    """Run every command in order (all of them, so one retry sees every failure).

    A command runs until it exits unless the caller gave it a ``timeout_s``; there is no default limit.
    """

    results: list[dict[str, Any]] = []
    for command in commands:
        try:
            result = await _run_one(
                command["cmd"],
                worktree,
                command.get("timeout_s"),
                tail_chars,
                drain_seconds,
            )
        except Exception as exc:  # a command that cannot start is a failed command, not an engine error
            result = {
                "cmd": command["cmd"],
                "exit_code": None,
                "timed_out": False,
                "duration_s": 0.0,
                "output_tail": f"could not run: {exc!r}",
            }
        result["passed"] = result["exit_code"] == 0
        results.append(result)
    return results


def passed(results: Sequence[Mapping[str, Any]]) -> bool:
    return all(r["passed"] for r in results)


def failure_note(results: Sequence[Mapping[str, Any]]) -> str:
    """What the next attempt is told: each failed command and the tail of its output."""

    parts = ["Your last attempt claimed to be done, but these acceptance commands failed. Fix the cause, then finish."]
    for result in results:
        if result["passed"]:
            continue
        how = "timed out" if result["timed_out"] else f"exit code {result['exit_code']}"
        parts.append(f"`{result['cmd']}` ({how}):\n```\n{result['output_tail']}\n```")
    return "\n\n".join(parts)
