"""Bash command execution for direct tool executor.

Handles subprocess spawning, output capture, and safety enforcement
for bash commands executed by agents.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.services.persona_policy import (
    command_hits_persona_git_publish_policy,
    get_persona_git_publish_block_reason,
)
from app.services.tools.command_guard import get_command_guard_block_reason
from app.utils.safe_subprocess import create_bash_process

logger = logging.getLogger(__name__)

# Maximum output size to return
MAX_OUTPUT_SIZE = 100_000


def get_persona_block_reason(command: str, agent_slug: str | None) -> str | None:
    """Return a persona-specific block reason for commands we never want in Bash."""
    if agent_slug != "persona":
        return None

    if command_hits_persona_git_publish_policy(command):
        return get_persona_git_publish_block_reason()
    return None


async def run_bash(
    command: str,
    working_dir: Path,
    env: dict[str, str],
    *,
    agent_slug: str | None = None,
    session_id: str | None = None,
    max_output_size: int | None = MAX_OUTPUT_SIZE,
) -> str:
    """Execute a bash command and return combined stdout+stderr output."""
    persona_block_reason = get_persona_block_reason(command, agent_slug)
    if persona_block_reason:
        return f"Error: Command blocked for workflow policy: {persona_block_reason}"

    guard_block_reason = get_command_guard_block_reason(
        command,
        working_dir,
        session_id=session_id,
    )
    if guard_block_reason:
        return guard_block_reason

    try:
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

        return output or "(no output)"

    except Exception as e:
        return f"Error executing command: {e}"
