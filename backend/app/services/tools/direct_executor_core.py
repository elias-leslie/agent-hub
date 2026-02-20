"""Core executor implementation for direct tool execution.

Handles bash command execution, file I/O, and agent consultation with
proper environment inheritance.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.services.tools.project_env import build_project_env
from app.services.tools.registry import get_command_redirect

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


def _get_command_redirect(command: str) -> str | None:
    """Check if command should be redirected to a standardized wrapper.

    Delegates to the centralized tool registry (tool-registry.json).
    Returns redirect message if command should use dt/st/restart scripts,
    None if the command is allowed to proceed.
    """
    return get_command_redirect(command)


class DirectToolExecutor:
    """Executes tools directly with environment inheritance.

    All operations run in the specified working directory with full
    access to the parent process environment variables.
    """

    def __init__(self, working_dir: str | None = None, project_id: str | None = None):
        """Initialize with working directory.

        Resolves the project's Python venv once at init. Handles worktrees
        by detecting the main repo and using its venv. All subprocess calls
        use this resolved environment.

        Args:
            working_dir: Base directory for all operations. Defaults to current dir.
            project_id: Project ID for agent consultation (enables consult_agent tool).
        """
        self.working_dir = Path(working_dir or ".").resolve()
        if not self.working_dir.exists():
            self.working_dir.mkdir(parents=True, exist_ok=True)
        self._env = build_project_env(self.working_dir)
        self._project_id = project_id

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

        redirect = _get_command_redirect(command)
        if redirect:
            return f"Error: Command redirected. {redirect}"

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.working_dir),
                env=self._env,
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
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = (self.working_dir / path).resolve()

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully wrote {len(content)} bytes to {path}"
        except Exception as e:
            return f"Error writing file: {e}"

    async def consult_agent(self, agent_slug: str, question: str, context: str = "") -> str:
        """Consult another agent for advice without executing tools.

        Makes a direct in-process call to complete_internal() to avoid
        HTTP self-call deadlock with single uvicorn worker.

        Args:
            agent_slug: Agent to consult (e.g., 'supervisor', 'reviewer')
            question: The question or problem description
            context: Optional additional context about the current situation

        Returns:
            The consulted agent's response text
        """
        if not self._project_id:
            return "Error: project_id not configured, cannot consult agent"

        prompt = question
        if context:
            prompt = f"Context:\n{context}\n\nQuestion:\n{question}"

        try:
            from app.api.complete.core import complete_internal
            from app.db import async_session
            from app.services.agent_routing_utils import resolve_agent

            async with async_session() as db:
                resolved = await resolve_agent(agent_slug, db)
                result = await complete_internal(
                    messages=[{"role": "user", "content": prompt}],
                    model=resolved.model,
                    provider=resolved.provider,
                    temperature=resolved.agent.temperature,
                    project_id=self._project_id,
                    db=db,
                    agent_slug=agent_slug,
                    use_memory=True,
                    memory_group_id=f"project-{self._project_id}",
                    max_turns=1,
                    execute_tools=False,
                )
                return result.content
        except Exception as e:
            logger.exception(f"consult_agent failed for '{agent_slug}'")
            return f"Error consulting agent '{agent_slug}': {e}"

    async def send_push(
        self,
        title: str,
        body: str,
        url: str | None = None,
        severity: str = "info",
        tag: str | None = None,
    ) -> str:
        """Send a push notification to all subscribed devices.

        Args:
            title: Notification title
            body: Notification body text
            url: Optional deep-link URL
            severity: info/warning/error/critical
            tag: Optional dedup tag

        Returns:
            Success message with delivery count
        """
        try:
            from app.db import async_session
            from app.services.push_service import send_push as _send_push

            payload: dict[str, str | None] = {
                "title": title,
                "body": body,
            }
            if url:
                payload["url"] = url
            if severity:
                payload["severity"] = severity
            if tag:
                payload["tag"] = tag

            async with async_session() as db:
                sent = await _send_push(db, payload=payload)

            return f"Push notification sent to {sent} device(s): {title}"
        except Exception as e:
            logger.exception("send_push failed")
            return f"Error sending push notification: {e}"
