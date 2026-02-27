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


def _persona_tool_registry() -> dict[str, Any]:
    """Return the registry subset for persona tools."""
    from app.services.tools._executor_persona import (
        mark_memory_irrelevant,
        mark_memory_relevant,
        read_journal,
        read_personality,
        read_user_context,
        search_journal,
        submit_onboarding,
        write_journal,
        write_personality,
        write_user_context,
    )
    return {
        "read_personality": read_personality,
        "write_personality": write_personality,
        "write_journal": write_journal,
        "read_journal": read_journal,
        "search_journal": search_journal,
        "write_user_context": write_user_context,
        "read_user_context": read_user_context,
        "mark_memory_relevant": mark_memory_relevant,
        "mark_memory_irrelevant": mark_memory_irrelevant,
        "submit_onboarding": submit_onboarding,
    }


def _schedule_tool_registry() -> dict[str, Any]:
    """Return the registry subset for scheduling tools."""
    from app.services.tools._executor_scheduling import (
        cancel_scheduled_job,
        list_scheduled_jobs,
        schedule_job,
    )
    return {
        "schedule_job": schedule_job,
        "list_scheduled_jobs": list_scheduled_jobs,
        "cancel_scheduled_job": cancel_scheduled_job,
    }


async def _manage_model_config(
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
    """Dispatch model management actions to the appropriate handler."""
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


def _model_tool_registry(bash_fn: Any) -> dict[str, Any]:
    """Return the registry subset for model management and I/O tools."""
    from app.services.tools._executor_io import manage_tasks, send_push

    async def _manage_tasks_bound(
        action: str,
        task_id: str | None = None,
        title: str | None = None,
        description: str | None = None,
        priority: int = 2,
        task_type: str = "task",
        labels: str | None = None,
    ) -> str:
        return await manage_tasks(
            bash_fn, action, task_id, title, description, priority, task_type, labels,
        )

    return {
        "send_push": send_push,
        "manage_tasks": _manage_tasks_bound,
        "manage_model_config": _manage_model_config,
    }


def _build_tool_registry(
    project_id: str | None,
    bash_fn: Any,
) -> dict[str, Any]:
    """Build a dispatch registry mapping tool names to async callables.

    Tools that are simple delegates to submodule functions are registered
    here so they do not need to be methods on DirectToolExecutor.
    Tools that require instance state (bash, read_file, write_file,
    consult_agent) remain as class methods and are not in this registry.
    """
    from app.services.tools._executor_consultation import (
        cancel_consultation,
        list_consultations,
        steer_consultation,
    )
    from app.services.tools._executor_performance import (
        log_agent_performance,
        review_agent_performance,
    )

    return {
        # Consultation
        "steer_consultation": steer_consultation,
        "list_consultations": list_consultations,
        "cancel_consultation": cancel_consultation,
        # Performance
        "log_agent_performance": log_agent_performance,
        "review_agent_performance": review_agent_performance,
        # Sub-registries merged in
        **_persona_tool_registry(),
        **_schedule_tool_registry(),
        **_model_tool_registry(bash_fn),
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
        """Initialize executor with optional working directory and project context.

        When working_dir is not provided (e.g. headless/worker contexts like
        heartbeat), falls back to the project's known root directory if available,
        rather than the process cwd which may be outside the project.
        """
        if working_dir is None and project_id and project_id in KNOWN_ROOTS:
            working_dir = KNOWN_ROOTS[project_id]
        self.working_dir = Path(working_dir or ".").resolve()
        if not self.working_dir.exists():
            self.working_dir.mkdir(parents=True, exist_ok=True)
        self._env = build_project_env(self.working_dir)
        self._project_id = project_id
        self._allowed_root: Path | None = self._resolve_project_root(project_id)
        self._registry: dict[str, Any] = _build_tool_registry(project_id, self.bash)

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
        """Route a tool call to the matching handler by name."""
        if name not in self.DISPATCHABLE_TOOLS:
            return f"Unknown tool: {name}"

        # Core instance methods handled directly
        if name == "bash":
            return await self.bash(**{k: v for k, v in args.items() if k in ("command", "timeout")})
        if name == "read_file":
            return await self.read_file(**{k: v for k, v in args.items() if k in ("path", "offset", "limit")})
        if name == "write_file":
            return await self.write_file(**{k: v for k, v in args.items() if k in ("path", "content")})
        if name == "consult_agent":
            return await self.consult_agent(**{k: v for k, v in args.items() if k in ("agent_slug", "question", "context")})

        # All other tools dispatched via registry
        fn = self._registry.get(name)
        if fn is None:
            return f"Unknown tool: {name}"
        params = inspect.signature(fn).parameters
        kwargs = {k: v for k, v in args.items() if k in params}
        try:
            return await fn(**kwargs)
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

    async def consult_agent(self, agent_slug: str, question: str, context: str = "") -> str:
        """Consult another agent for advice without executing tools."""
        from app.services.tools._executor_consultation import consult_agent as _consult
        return await _consult(self._project_id, agent_slug, question, context)
