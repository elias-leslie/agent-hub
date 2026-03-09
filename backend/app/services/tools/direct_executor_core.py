"""Core executor implementation for direct tool execution.

Handles bash command execution, file I/O, and agent consultation with
proper environment inheritance.
"""

from __future__ import annotations

import inspect
import logging
from pathlib import Path
from typing import Any, ClassVar

from app.services.tools._executor_bash import (
    BLOCKED_COMMANDS as BLOCKED_COMMANDS,
)
from app.services.tools._executor_bash import (
    DEFAULT_TIMEOUT,
    is_blocked_command,
    run_bash,
)
from app.services.tools._executor_bash import (
    MAX_OUTPUT_SIZE as MAX_OUTPUT_SIZE,
)
from app.services.tools._executor_file_io import (
    _is_path_allowed as _check_path_allowed,
)
from app.services.tools._executor_file_io import (
    read_file as _read_file,
)
from app.services.tools._executor_file_io import (
    write_file as _write_file,
)
from app.services.tools._executor_registry import build_tool_registry
from app.services.tools.catalog import search_tool_catalog
from app.services.tools.project_env import build_project_env
from app.services.tools.registry import get_command_redirect

logger = logging.getLogger(__name__)

# Dynamic project roots — derived from project_permissions table.
# Used for path boundary enforcement and cross-project permission checks.
# Projects NOT in the map (e.g. persona-sandbox with no root_path) have no path restriction.


def _get_known_roots() -> dict[str, str]:
    """Get project_id → root_path mapping from cached project data."""
    from app.constants.projects import get_known_roots

    return get_known_roots()


# Backward-compatible module-level name for imports (e.g. cross_project_hook).
# Callers that do `from ... import KNOWN_ROOTS` then `KNOWN_ROOTS.get(pid)`
# need a proxy that delegates to the cached function.


class _RootsProxy(dict):
    """Dict-like proxy that delegates to get_known_roots()."""

    def get(self, key: str, default: str | None = None) -> str | None:
        return _get_known_roots().get(key, default)

    def __getitem__(self, key: str) -> str:
        return _get_known_roots()[key]

    def __contains__(self, key: object) -> bool:
        return key in _get_known_roots()

    def __iter__(self):
        return iter(_get_known_roots())

    def items(self):
        return _get_known_roots().items()

    def values(self):
        return _get_known_roots().values()

    def keys(self):
        return _get_known_roots().keys()

    def __repr__(self) -> str:
        return repr(_get_known_roots())


KNOWN_ROOTS: dict[str, str] = _RootsProxy()  # type: ignore[assignment]


def _is_blocked_command(command: str) -> bool:
    """Check if command is blocked for safety."""
    return is_blocked_command(command)


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

    DISPATCHABLE_TOOLS: ClassVar[frozenset[str]] = frozenset({
        "bash", "read_file", "write_file", "consult_agent", "dispatch_agent",
        "tool_search",
        "read_personality", "write_personality",
        "write_user_context", "read_user_context",
        "read_heartbeat_instructions", "write_heartbeat_instructions",
        "mark_memory_relevant", "mark_memory_irrelevant",
        "submit_onboarding", "send_push",
        "schedule_job", "list_scheduled_jobs", "cancel_scheduled_job",
        "steer_consultation", "list_consultations", "cancel_consultation",
        "manage_tasks", "manage_backups", "manage_model_config", "manage_feedback",
        "log_agent_performance", "review_agent_performance",
        "query_sessions", "inspect_session",
    })

    def __init__(
        self,
        working_dir: str | None = None,
        project_id: str | None = None,
        session_id: str | None = None,
        tool_catalog: list[dict[str, Any]] | None = None,
    ):
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
        self._session_id = session_id
        self._tool_catalog = {
            str(tool["name"]): dict(tool) for tool in (tool_catalog or [])
        }
        root = KNOWN_ROOTS.get(project_id) if project_id else None
        self._allowed_root: Path | None = Path(root) if root else None
        self._registry: dict[str, Any] = build_tool_registry(project_id, self.bash)

    def _is_path_allowed(self, path: Path) -> bool:
        """Check if a resolved path is within the project's allowed root or working dir."""
        return _check_path_allowed(path, self._allowed_root, extra_roots=(self.working_dir,))

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
        if name == "dispatch_agent":
            return await self.dispatch_agent(**{k: v for k, v in args.items() if k in ("agent_slug", "task", "project_id", "max_turns")})
        if name == "tool_search":
            return await self.tool_search(**{k: v for k, v in args.items() if k in ("query", "limit")})

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

    async def bash(self, command: str, timeout: int = DEFAULT_TIMEOUT) -> str:
        """Execute a bash command with environment inheritance."""
        if _is_blocked_command(command):
            return f"Error: Command blocked for safety: {command}"

        redirect = _get_command_redirect(command)
        if redirect:
            return f"Error: Command redirected. {redirect}"

        if self._allowed_root and not self._is_path_allowed(self.working_dir):
            return "Error: Working directory outside allowed project root"

        return await run_bash(command, self.working_dir, self._env, timeout)

    async def read_file(self, path: str, offset: int = 0, limit: int = 2000) -> str:
        """Read a file with optional line offset and limit."""
        return await _read_file(path, self.working_dir, self._allowed_root, offset, limit)

    async def write_file(self, path: str, content: str) -> str:
        """Write a file."""
        return await _write_file(path, content, self.working_dir, self._allowed_root)

    async def consult_agent(self, agent_slug: str, question: str, context: str = "") -> str:
        """Consult another agent for advice without executing tools."""
        from app.services.tools._executor_consultation import consult_agent as _consult
        return await _consult(self._project_id, agent_slug, question, context)

    async def dispatch_agent(
        self, agent_slug: str, task: str,
        project_id: str | None = None, max_turns: int = 25,
    ) -> str:
        """Dispatch an agent with full tool access to perform a task."""
        from app.services.tools._executor_consultation import dispatch_agent as _dispatch
        # Use provided project_id (from tool args) or fall back to executor's project
        effective_project_id = project_id or self._project_id
        return await _dispatch(
            effective_project_id,
            agent_slug,
            task,
            max_turns,
            parent_session_id=self._session_id,
        )

    async def tool_search(self, query: str, limit: int = 8) -> str:
        """Search the available tool catalog and return matching tools as JSON."""
        if not self._tool_catalog:
            return 'Error: No tool catalog available for this run.'
        return search_tool_catalog(self._tool_catalog.values(), query, limit)

    def has_catalog_tool(self, name: str) -> bool:
        """Return True when a named tool exists in the current catalog."""
        return bool(name) and name in self._tool_catalog
