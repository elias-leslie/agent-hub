"""Bash command execution for direct tool executor.

Handles subprocess spawning, output capture, and safety enforcement
for bash commands executed by agents.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from contextlib import suppress
from pathlib import Path

from app.config import settings
from app.services.tools.command_guard import get_command_guard_block_reason
from app.services.workflow_runs.processes import current_tracker, start_tracked
from app.utils.safe_subprocess import bash_argv, create_bash_process

logger = logging.getLogger(__name__)

# Inline output budget; larger bash output is spilled to a scratch artifact.
MAX_OUTPUT_SIZE = settings.tool_output_inline_chars
PROCESS_CANCEL_GRACE_SECONDS = 2.0


async def run_bash(
    command: str,
    working_dir: Path,
    env: dict[str, str],
    *,
    session_id: str | None = None,
    max_output_size: int | None = MAX_OUTPUT_SIZE,
) -> str:
    """Execute a bash command and return combined stdout+stderr output."""
    guard_block_reason = await asyncio.to_thread(
        get_command_guard_block_reason,
        command,
        working_dir,
        session_id=session_id,
    )
    if guard_block_reason:
        return guard_block_reason

    process = None
    tracked = None
    try:
        if current_tracker.get() is not None:
            # A workflow attempt's command: recorded with the attempt (identity, marker, parent-death signal), so
            # a cancel or a crash recovery can stop it and anything it left behind.
            tracked = await start_tracked(*bash_argv(command), kind="tool", working_dir=working_dir, env=env)
            process = tracked.process
        else:
            process = await create_bash_process(
                command,
                working_dir=working_dir,
                env=env,
            )

        stdout, stderr = await process.communicate()

        output = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")

        if stderr_text:
            output = output + stderr_text

        if max_output_size is not None and len(output) > max_output_size:
            output = output[:max_output_size] + "\n... (output truncated)"

        # Without the status the model cannot tell a quiet failure from success and reruns to check.
        if process.returncode:
            return f"{output}\n\nCommand exited with code {process.returncode}".lstrip()
        return output or "(no output)"

    except asyncio.CancelledError:
        if process is not None:
            await _terminate_cancelled_process(process)
        raise
    except Exception as e:
        return f"Error executing command: {e}"
    finally:
        if tracked is not None:
            tracker = current_tracker.get()
            if tracker is not None:
                await asyncio.shield(tracker.release(tracked))


async def _terminate_cancelled_process(process: asyncio.subprocess.Process) -> None:
    """Terminate a cancelled bash command and its process group."""
    if process.returncode is not None:
        return

    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    with suppress(asyncio.TimeoutError):
        await asyncio.wait_for(process.wait(), timeout=PROCESS_CANCEL_GRACE_SECONDS)
        return

    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    with suppress(Exception):
        await process.wait()
