"""Direct tool executors for agent tool execution.

Executes bash, read, and write tools directly with proper environment
inheritance. Commands run in the specified working directory with full
access to parent environment variables.

Replaces sandboxed_executor.py which added unnecessary subprocess layering.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from app.services.tools.base import Tool, ToolCall, ToolHandler, ToolResult

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
    }
)


def _is_blocked_command(command: str) -> bool:
    """Check if command is blocked for safety."""
    command_lower = command.lower().strip()
    return any(blocked in command_lower for blocked in BLOCKED_COMMANDS)


class DirectToolExecutor:
    """Executes tools directly with environment inheritance.

    All operations run in the specified working directory with full
    access to the parent process environment variables.
    """

    def __init__(self, working_dir: str | None = None):
        """Initialize with working directory.

        Args:
            working_dir: Base directory for all operations. Defaults to current dir.
        """
        self.working_dir = Path(working_dir or ".").resolve()
        if not self.working_dir.exists():
            self.working_dir.mkdir(parents=True, exist_ok=True)

    async def bash(self, command: str, timeout: int = DEFAULT_TIMEOUT) -> str:
        """Execute a bash command with environment inheritance.

        Args:
            command: The command to execute
            timeout: Timeout in seconds (default 120)

        Returns:
            Command output (stdout + stderr)
        """
        if _is_blocked_command(command):
            return f"Error: Command blocked for safety: {command}"

        try:
            # Explicitly inherit parent environment
            env = os.environ.copy()

            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.working_dir),
                env=env,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )

            output = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")

            # Combine stdout and stderr
            if stderr_text:
                output = output + stderr_text

            if len(output) > MAX_OUTPUT_SIZE:
                output = output[:MAX_OUTPUT_SIZE] + "\n... (output truncated)"

            return output or "(no output)"

        except TimeoutError:
            return f"Error: Command timed out after {timeout}s"
        except Exception as e:
            return f"Error executing command: {e}"

    async def read_file(self, path: str, offset: int = 0, limit: int = 2000) -> str:
        """Read a file.

        Args:
            path: File path (absolute or relative to working dir)
            offset: Line offset (0-indexed)
            limit: Max lines to read

        Returns:
            File contents with line numbers
        """
        # Handle both absolute and relative paths
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = (self.working_dir / path).resolve()

        if not file_path.exists():
            return f"Error: File not found: {path}"
        if file_path.is_dir():
            return f"Error: Path is a directory: {path}"

        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            total_lines = len(lines)
            selected = lines[offset : offset + limit]

            # Format with line numbers
            result_lines = []
            for i, line in enumerate(selected, start=offset + 1):
                result_lines.append(f"{i:6}\t{line.rstrip()}")

            result = "\n".join(result_lines)

            if offset + limit < total_lines:
                result += f"\n... ({total_lines - offset - limit} more lines)"

            return result or "(empty file)"

        except Exception as e:
            return f"Error reading file: {e}"

    async def write_file(self, path: str, content: str) -> str:
        """Write a file.

        Args:
            path: File path (absolute or relative to working dir)
            content: File content

        Returns:
            Success or error message
        """
        # Handle both absolute and relative paths
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = (self.working_dir / path).resolve()

        try:
            # Create parent directories if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            return f"Successfully wrote {len(content)} bytes to {path}"

        except Exception as e:
            return f"Error writing file: {e}"


# Standard tool definitions for agents
STANDARD_TOOLS = [
    Tool(
        name="bash",
        description="Execute a bash command in the working directory. Use for running tests, git operations, or system commands.",
        input_schema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 120)",
                    "default": DEFAULT_TIMEOUT,
                },
            },
            "required": ["command"],
        },
    ),
    Tool(
        name="read_file",
        description="Read contents of a file. Returns lines with line numbers.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path (absolute or relative to working directory)",
                },
                "offset": {
                    "type": "integer",
                    "description": "Line offset to start reading from (0-indexed)",
                    "default": 0,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read",
                    "default": 2000,
                },
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="write_file",
        description="Write content to a file. Creates parent directories if needed.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path (absolute or relative to working directory)",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file",
                },
            },
            "required": ["path", "content"],
        },
    ),
]


class DirectToolHandler(ToolHandler):
    """Tool handler that uses direct executor."""

    def __init__(self, working_dir: str | None = None):
        """Initialize with working directory.

        Args:
            working_dir: Base directory for all operations
        """
        super().__init__()
        self._executor = DirectToolExecutor(working_dir)

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call."""
        try:
            if tool_call.name == "bash":
                output = await self._executor.bash(
                    command=tool_call.input.get("command", ""),
                    timeout=tool_call.input.get("timeout", DEFAULT_TIMEOUT),
                )
            elif tool_call.name == "read_file":
                output = await self._executor.read_file(
                    path=tool_call.input.get("path", ""),
                    offset=tool_call.input.get("offset", 0),
                    limit=tool_call.input.get("limit", 2000),
                )
            elif tool_call.name == "write_file":
                output = await self._executor.write_file(
                    path=tool_call.input.get("path", ""),
                    content=tool_call.input.get("content", ""),
                )
            else:
                output = f"Unknown tool: {tool_call.name}"

            return ToolResult(
                tool_use_id=tool_call.id,
                content=output,
                is_error=output.startswith("Error:"),
            )

        except Exception as e:
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Tool execution error: {e}",
                is_error=True,
            )


def get_standard_tools() -> list[Tool]:
    """Get standard tool definitions."""
    return STANDARD_TOOLS.copy()


def create_direct_handler(working_dir: str | None = None) -> DirectToolHandler:
    """Create a direct tool handler.

    Args:
        working_dir: Base directory for tool operations

    Returns:
        DirectToolHandler configured for the directory
    """
    return DirectToolHandler(working_dir)
