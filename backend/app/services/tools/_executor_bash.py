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


def is_blocked_command(command: str) -> bool:
    """Check if command is blocked for safety."""
    command_lower = command.lower().strip()
    return any(blocked in command_lower for blocked in BLOCKED_COMMANDS)


async def run_bash(
    command: str,
    working_dir: Path,
    env: dict[str, str],
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """Execute a bash command and return combined stdout+stderr output."""
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
