"""Core executor implementation for direct tool execution.

Handles bash command execution, file I/O, and agent consultation with
proper environment inheritance.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from pathlib import Path
from typing import Any, ClassVar

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


# Known project roots — maps project_id to filesystem root.
# Used for path boundary enforcement and cross-project permission checks.
# Projects NOT in this map (e.g. persona-sandbox) have no path restriction.
KNOWN_ROOTS: dict[str, str] = {
    "summitflow": "/home/kasadis/summitflow",
    "agent-hub": "/home/kasadis/agent-hub",
    "portfolio-ai": "/home/kasadis/portfolio-ai",
    "terminal": "/home/kasadis/terminal",
    "monkey-fight": "/home/kasadis/monkey-fight",
}


class DirectToolExecutor:
    """Executes tools directly with environment inheritance.

    All operations run in the specified working directory with full
    access to the parent process environment variables.
    """

    DISPATCHABLE_TOOLS: ClassVar[frozenset[str]] = frozenset({
        "bash", "read_file", "write_file", "consult_agent",
        "read_personality", "write_personality",
        "write_journal", "read_journal", "search_journal",
        "write_user_context", "read_user_context",
        "mark_memory_relevant", "mark_memory_irrelevant",
        "submit_onboarding", "send_push",
        "schedule_job", "list_scheduled_jobs", "cancel_scheduled_job",
        "steer_consultation", "list_consultations", "cancel_consultation",
        "manage_tasks", "manage_model_config",
        "log_agent_performance", "review_agent_performance",
    })

    def __init__(self, working_dir: str | None = None, project_id: str | None = None):
        """Initialize executor with optional working directory and project context."""
        self.working_dir = Path(working_dir or ".").resolve()
        if not self.working_dir.exists():
            self.working_dir.mkdir(parents=True, exist_ok=True)
        self._env = build_project_env(self.working_dir)
        self._project_id = project_id
        self._allowed_root: Path | None = self._resolve_project_root(project_id)

    @staticmethod
    def _resolve_project_root(project_id: str | None) -> Path | None:
        """Resolve the allowed root path for a project."""
        if not project_id:
            return None
        root = KNOWN_ROOTS.get(project_id)
        return Path(root) if root else None

    def _is_path_allowed(self, path: Path) -> bool:
        """Check if a resolved path is within the project's allowed root."""
        if not self._allowed_root:
            return True
        try:
            path.resolve().relative_to(self._allowed_root)
            return True
        except ValueError:
            return False

    async def dispatch(self, name: str, args: dict[str, Any]) -> str:
        """Route a tool call to the matching method by name."""
        if name not in self.DISPATCHABLE_TOOLS:
            return f"Unknown tool: {name}"
        method = getattr(self, name)
        params = inspect.signature(method).parameters
        kwargs = {k: v for k, v in args.items() if k in params}
        try:
            return await method(**kwargs)
        except TypeError as e:
            return f"Invalid arguments for {name}: {e}"

    # --- Core I/O tools ---

    async def bash(self, command: str, timeout: int = DEFAULT_TIMEOUT) -> str:
        """Execute a bash command with environment inheritance."""
        if _is_blocked_command(command):
            return f"Error: Command blocked for safety: {command}"

        redirect = _get_command_redirect(command)
        if redirect:
            return f"Error: Command redirected. {redirect}"

        if self._allowed_root and not self._is_path_allowed(self.working_dir):
            return "Error: Working directory outside allowed project root"

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
        """Read a file with optional line offset and limit."""
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = (self.working_dir / path).resolve()

        if not self._is_path_allowed(file_path):
            return f"Error: Path outside allowed project root: {path}"

        if not file_path.exists():
            return f"Error: File not found: {path}"
        if file_path.is_dir():
            return f"Error: Path is a directory: {path}"

        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            total_lines = len(lines)
            selected = lines[offset : offset + limit]

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
        """Write a file."""
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = (self.working_dir / path).resolve()

        if not self._is_path_allowed(file_path):
            return f"Error: Path outside allowed project root: {path}"

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully wrote {len(content)} bytes to {path}"
        except Exception as e:
            return f"Error writing file: {e}"

    # --- Consultation tools ---

    async def consult_agent(self, agent_slug: str, question: str, context: str = "") -> str:
        """Consult another agent for advice without executing tools."""
        from app.services.tools._executor_consultation import consult_agent as _consult
        return await _consult(self._project_id, agent_slug, question, context)

    async def steer_consultation(self, session_id: str, message: str) -> str:
        """Send a follow-up message to an existing consultation session."""
        from app.services.tools._executor_consultation import steer_consultation as _steer
        return await _steer(self._project_id, session_id, message)

    async def list_consultations(
        self, hours_back: int = 24, agent_slug: str | None = None,
    ) -> str:
        """List recent consultation sessions."""
        from app.services.tools._executor_consultation import list_consultations as _list
        return await _list(hours_back, agent_slug)

    async def cancel_consultation(self, session_id: str) -> str:
        """Close a running consultation session."""
        from app.services.tools._executor_consultation import cancel_consultation as _cancel
        return await _cancel(session_id)

    # --- Persona tools ---

    async def read_personality(self) -> str:
        """Read the persona's current personality document."""
        from app.services.tools._executor_persona import read_personality as _read
        return await _read()

    async def write_personality(self, personality: str, reason: str) -> str:
        """Update the persona's personality document."""
        from app.services.tools._executor_persona import write_personality as _write
        return await _write(personality, reason)

    async def write_journal(self, content: str, entry_type: str = "observation") -> str:
        """Write a journal entry for today."""
        from app.services.tools._executor_persona import write_journal as _write
        return await _write(content, entry_type)

    async def read_journal(self, days_back: int = 7) -> str:
        """Read recent journal entries."""
        from app.services.tools._executor_persona import read_journal as _read
        return await _read(days_back)

    async def search_journal(self, query: str, days_back: int = 30) -> str:
        """Search journal entries by content."""
        from app.services.tools._executor_persona import search_journal as _search
        return await _search(query, days_back)

    async def write_user_context(self, user_context: str) -> str:
        """Update the persona's user context document."""
        from app.services.tools._executor_persona import write_user_context as _write
        return await _write(user_context)

    async def read_user_context(self) -> str:
        """Read the persona's current user context."""
        from app.services.tools._executor_persona import read_user_context as _read
        return await _read()

    async def mark_memory_relevant(self, memory_uuid: str) -> str:
        """Add 'persona-relevant' tag to a memory episode."""
        from app.services.tools._executor_persona import mark_memory_relevant as _mark
        return await _mark(memory_uuid)

    async def mark_memory_irrelevant(self, memory_uuid: str) -> str:
        """Remove 'persona-relevant' tag from a memory episode."""
        from app.services.tools._executor_persona import mark_memory_irrelevant as _mark
        return await _mark(memory_uuid)

    async def submit_onboarding(self, summary: str) -> str:
        """Submit the onboarding profile for dual-model approval."""
        from app.services.tools._executor_persona import submit_onboarding as _submit
        return await _submit(summary)

    # --- Push notifications ---

    async def send_push(
        self,
        title: str,
        body: str,
        url: str | None = None,
        severity: str = "info",
        tag: str | None = None,
    ) -> str:
        """Send a push notification to all subscribed devices."""
        try:
            from app.db import async_session
            from app.services.push_service import send_push as _send_push

            payload: dict[str, str | None] = {"title": title, "body": body}
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

    # --- Scheduling tools ---

    async def schedule_job(
        self,
        name: str,
        schedule_type: str,
        schedule_value: str,
        payload_message: str,
        payload_type: str = "agent_turn",
        delivery: str = "none",
        timezone: str = "UTC",
    ) -> str:
        """Create a scheduled job for the persona."""
        from app.services.tools._executor_scheduling import schedule_job as _schedule
        return await _schedule(
            name, schedule_type, schedule_value, payload_message,
            payload_type, delivery, timezone,
        )

    async def list_scheduled_jobs(self, include_disabled: bool = False) -> str:
        """List scheduled jobs for the persona."""
        from app.services.tools._executor_scheduling import list_scheduled_jobs as _list
        return await _list(include_disabled)

    async def cancel_scheduled_job(
        self, job_id: str, hard_delete: bool = False,
    ) -> str:
        """Disable or delete a scheduled job."""
        from app.services.tools._executor_scheduling import cancel_scheduled_job as _cancel
        return await _cancel(job_id, hard_delete)

    # --- Task orchestration ---

    async def manage_tasks(
        self,
        action: str,
        task_id: str | None = None,
        title: str | None = None,
        description: str | None = None,
        priority: int = 2,
        task_type: str = "task",
        labels: str | None = None,
    ) -> str:
        """Quick task operations via st CLI."""
        if action == "list_ready":
            return await self.bash("st ready")

        if action == "get_context":
            if not task_id:
                return "Error: task_id required for get_context"
            return await self.bash(f"st context {task_id}")

        if action == "create":
            if not title:
                return "Error: title required for create"
            cmd = f"st create '{title}' -t {task_type} -p {priority}"
            if description:
                cmd += f" -d '{description}'"
            if labels:
                cmd += f" -l '{labels}'"
            logger.info("manage_tasks create: %s", cmd)
            return await self.bash(cmd)

        if action == "dispatch":
            if not task_id:
                return "Error: task_id required for dispatch"
            return await self.bash(f"st autocode {task_id}")

        return f"Error: Unknown action '{action}'. Use list_ready/get_context/create/dispatch."

    # --- Model management ---

    async def manage_model_config(
        self,
        action: str,
        model_id: str | None = None,
        agent_slug: str | None = None,
        primary_model_id: str | None = None,
        fallback_models: list[str] | None = None,
        escalation_model_id: str | None = None,
        temperature: float | None = None,
        thinking_level: str | None = None,
        change_reason: str | None = None,
    ) -> str:
        """Manage model configurations across agents."""
        from app.services.tools._executor_model_mgmt import (
            get_benchmarks,
            get_model_details,
            list_agents,
            list_models,
            update_agent_model,
        )

        if action == "list_models":
            return await list_models()
        if action == "get_model_details":
            return await get_model_details(model_id)
        if action == "update_agent_model":
            return await update_agent_model(
                agent_slug, primary_model_id, fallback_models,
                escalation_model_id, temperature, thinking_level, change_reason,
            )
        if action == "get_benchmarks":
            return await get_benchmarks()
        if action == "list_agents":
            return await list_agents()
        return (
            f"Error: Unknown action '{action}'. "
            "Use list_models/get_model_details/update_agent_model/get_benchmarks/list_agents."
        )

    # --- Performance tracking ---

    async def log_agent_performance(
        self,
        agent_slug: str,
        model_id: str,
        feedback_type: str,
        content: str,
        outcome: str = "success",
        task_type: str | None = None,
        project_id: str | None = None,
        session_id: str | None = None,
        duration_ms: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        tool_calls_count: int | None = None,
        turns: int | None = None,
    ) -> str:
        """Log a performance observation for an agent/model combination."""
        from app.services.tools._executor_performance import log_agent_performance as _log
        return await _log(
            agent_slug, model_id, feedback_type, content, outcome,
            task_type, project_id, session_id, duration_ms,
            input_tokens, output_tokens, tool_calls_count, turns,
        )

    async def review_agent_performance(
        self,
        agent_slug: str | None = None,
        model_id: str | None = None,
        feedback_type: str | None = None,
        days_back: int = 30,
        limit: int = 50,
    ) -> str:
        """Review performance history for agents and models."""
        from app.services.tools._executor_performance import review_agent_performance as _review
        return await _review(agent_slug, model_id, feedback_type, days_back, limit)
