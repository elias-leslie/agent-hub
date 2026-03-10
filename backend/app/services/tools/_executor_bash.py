"""Bash command execution for direct tool executor.

Handles subprocess spawning, output capture, and safety enforcement
for bash commands executed by agents.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Maximum output size to return
MAX_OUTPUT_SIZE = 100_000

# Default timeout for commands
DEFAULT_TIMEOUT = 120

# Blocked commands for safety (destructive system commands)
BLOCKED_COMMANDS = frozenset(
    {
        "rm -rf /",
        "rm -rf /*",
        "mkfs",
        "dd if=/dev/zero",
        "> /dev/sda",
        # Git safety — agents must use st CLI for task work
        "git push --force",
        "git push -f",
        "git reset --hard",
        "git clean -fd",
        "git clean -f",
        "git checkout .",
        # Service safety — agents must use wrapper scripts
        "systemctl stop",
        "systemctl disable",
        "drop database",
        "drop table",
        "truncate",
    }
)

_PERSONA_BLOCKED_SUBSTRINGS = (
    "git commit",
    "git push ",
)


def is_blocked_command(command: str) -> bool:
    """Check if command is blocked for safety."""
    command_lower = command.lower().strip()
    return any(blocked in command_lower for blocked in BLOCKED_COMMANDS)


def get_persona_block_reason(command: str, agent_slug: str | None) -> str | None:
    """Return a Jenny-specific block reason for commands we never want in Bash."""
    if agent_slug != "persona":
        return None

    command_lower = command.lower().strip()
    if any(blocked in command_lower for blocked in _PERSONA_BLOCKED_SUBSTRINGS):
        return (
            "Jenny must not use raw git commit/push from Bash. "
            "Use manage_tasks(action='smart_sync', project_id='...') for coherent publish debt, "
            "or the canonical commit.sh flow only when direct code intervention is operationally required."
        )
    return None


async def run_bash(
    command: str,
    working_dir: Path,
    env: dict[str, str],
    timeout: int = DEFAULT_TIMEOUT,
    agent_slug: str | None = None,
) -> str:
    """Execute a bash command and return combined stdout+stderr output."""
    persona_block_reason = get_persona_block_reason(command, agent_slug)
    if persona_block_reason:
        return f"Error: Command blocked for workflow policy: {persona_block_reason}"

    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(working_dir),
            env=env,
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout,
        )

        output = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")

        if stderr_text:
            output = output + stderr_text

        if len(output) > MAX_OUTPUT_SIZE:
            output = output[:MAX_OUTPUT_SIZE] + "\n... (output truncated)"

        return output or "(no output)"

    except TimeoutError:
        return f"Error: Command timed out after {timeout}s"
    except Exception as e:
        return f"Error executing command: {e}"
