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
    MAX_OUTPUT_SIZE as MAX_OUTPUT_SIZE,
)
from app.services.tools._executor_bash import (
    run_bash,
)
from app.services.tools._executor_file_io import (
    _is_path_allowed as _check_path_allowed,
)
from app.services.tools._executor_file_io import (
    edit_file as _edit_file,
)
from app.services.tools._executor_file_io import (
    read_file as _read_file,
)
from app.services.tools._executor_file_io import (
    write_file as _write_file,
)
from app.services.tools._executor_registry import build_tool_registry
from app.services.tools._executor_restart_guards import (
    _in_band_agent_hub_restart_block_reason,
    _rewrite_in_band_agent_hub_restart,
    _self_hosting_restart_block_reason,
)
from app.services.tools._executor_roots import KNOWN_ROOTS as KNOWN_ROOTS
from app.services.tools._executor_web import (
    fetch_web_page as _fetch_web_page,
)
from app.services.tools._executor_web import (
    research_web as _research_web,
)
from app.services.tools._executor_web import (
    search_web as _search_web,
)
from app.services.tools._sensitive_content import scan_runtime_sensitive_content
from app.services.tools.catalog import search_tool_catalog
from app.services.tools.project_env import build_project_env
from app.services.tools.registry import get_command_redirect
from app.services.tools.scratch_context import (
    ScratchContextStore,
    ScratchOutputResult,
    inline_output_result,
)

logger = logging.getLogger(__name__)

_get_command_redirect = get_command_redirect

BATCH_OUTPUT_THRESHOLD = 12_000
MAX_BATCH_COMMANDS = 8


def _is_error_output(output: str) -> bool:
    return output.startswith("Error:") or output.startswith("Unknown tool:") or output.startswith("BLOCKED:")


def _clamp_inline(text: str, limit: int = 8_000) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 28)].rstrip() + "\n... [truncated]"


class DirectToolExecutor:
    """Executes tools directly with environment inheritance.

    All operations run in the specified working directory with full
    access to the parent process environment variables.
    """

    DISPATCHABLE_TOOLS: ClassVar[frozenset[str]] = frozenset({
        "bash", "read_file", "write_file", "search_scratch_context", "batch_execute",
        "edit_file",
        "consult_agent", "dispatch_agent",
        "precision_code_search", "research_web", "search_web", "fetch_web_page", "tool_search",
        "propose_thorough", "propose_committee", "propose_honing",
        "read_personality", "write_personality",
        "write_user_context", "read_user_context",
        "read_heartbeat_instructions", "write_heartbeat_instructions",
        "mark_memory_relevant", "mark_memory_irrelevant", "manage_memory_tags",
        "review_memory_system", "submit_onboarding", "send_push",
        "schedule_job", "list_scheduled_jobs", "cancel_scheduled_job",
        "steer_consultation", "list_consultations", "cancel_consultation",
        "manage_tasks", "manage_backups", "manage_model_config", "manage_feedback",
        "log_agent_performance", "review_agent_performance", "review_improvement_signals",
        "query_sessions", "inspect_session", "search_persona_history",
    })

    def __init__(
        self,
        working_dir: str | None = None,
        project_id: str | None = None,
        session_id: str | None = None,
        agent_slug: str | None = None,
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
        self._agent_slug = agent_slug
        self._scratch_context = ScratchContextStore()
        if session_id:
            self._env["AGENT_HUB_SESSION_ID"] = session_id
        self._tool_catalog = {
            str(tool["name"]): dict(tool) for tool in (tool_catalog or [])
        }
        root = KNOWN_ROOTS.get(project_id) if project_id else None
        self._allowed_root: Path | None = Path(root) if root else None
        self._registry: dict[str, Any] = build_tool_registry(project_id, self.bash)

    def _is_path_allowed(self, path: Path) -> bool:
        """Check if a resolved path is within the project's allowed root or working dir."""
        return _check_path_allowed(path, self._allowed_root, extra_roots=(self.working_dir,))

    async def _allowed_root_for_file_tool(
        self,
        path: str,
        *,
        write: bool,
    ) -> tuple[Path | None, str | None]:
        """Return the project root allowed for a file tool path, or a block reason."""
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = (self.working_dir / path).resolve()

        if self._is_path_allowed(file_path):
            return self._allowed_root, None
        if not self._project_id:
            return self._allowed_root, None

        from app.services.tools._cross_project_hook import _infer_target_project, _resolve_tier

        target_project = _infer_target_project(file_path, KNOWN_ROOTS)
        if target_project is None:
            return self._allowed_root, None

        tier = await _resolve_tier(target_project)
        if tier is None or tier == "off":
            return None, f"Project permission denied for {target_project}: {tier or 'missing'}"
        if write and tier == "read":
            return None, f"Project permission denied for {target_project}: read-only"

        target_root = KNOWN_ROOTS.get(target_project)
        return (Path(target_root) if target_root else self._allowed_root), None

    async def dispatch(self, name: str, args: dict[str, Any]) -> str:
        """Route a tool call to the matching handler by name."""
        if name not in self.DISPATCHABLE_TOOLS:
            return f"Unknown tool: {name}"

        # Core instance methods handled directly
        if name == "bash":
            return await self.bash(**{k: v for k, v in args.items() if k == "command"})
        if name == "read_file":
            return await self.read_file(**{k: v for k, v in args.items() if k in ("path", "offset", "limit")})
        if name == "write_file":
            return await self.write_file(
                **{k: v for k, v in args.items() if k in ("path", "content", "allow_large_truncate")}
            )
        if name == "edit_file":
            return await self.edit_file(
                **{k: v for k, v in args.items() if k in ("path", "old_text", "new_text", "replace_all")}
            )
        if name == "search_scratch_context":
            return await self.search_scratch_context(
                **{
                    k: v
                    for k, v in args.items()
                    if k in ("query", "artifact_id", "limit", "context_lines")
                }
            )
        if name == "batch_execute":
            return await self.batch_execute(
                **{k: v for k, v in args.items() if k in ("commands", "stop_on_error")}
            )
        if name == "consult_agent":
            return await self.consult_agent(**{k: v for k, v in args.items() if k in ("agent_slug", "question", "context")})
        if name == "dispatch_agent":
            return await self.dispatch_agent(**{k: v for k, v in args.items() if k in ("agent_slug", "task", "project_id", "max_turns")})
        if name == "search_web":
            return await _search_web(
                query=args["query"],
                max_results=args.get("max_results", 5),
                search_type=args.get("search_type", "text"),
                timelimit=args.get("timelimit"),
            )
        if name == "research_web":
            return await _research_web(
                query=args["query"],
                max_results=args.get("max_results", 5),
                result_index=args.get("result_index", 1),
                search_type=args.get("search_type", "text"),
                timelimit=args.get("timelimit"),
                max_chars=args.get("max_chars", 12000),
                focus_query=args.get("focus_query"),
            )
        if name == "fetch_web_page":
            return await _fetch_web_page(
                url=args["url"],
                max_chars=args.get("max_chars", 12000),
                focus_query=args.get("focus_query"),
            )
        if name == "propose_thorough":
            from app.services.tools._propose_tools import execute_propose_thorough

            return execute_propose_thorough(args)
        if name == "propose_committee":
            from app.services.tools._propose_tools import execute_propose_committee

            return execute_propose_committee(args)
        if name == "propose_honing":
            from app.services.tools._propose_tools import execute_propose_honing

            return execute_propose_honing(args)
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

    async def _run_bash_process(self, command: str, *, threshold: int) -> ScratchOutputResult:
        output = await run_bash(
            command,
            self.working_dir,
            self._env,
            agent_slug=self._agent_slug,
            session_id=self._session_id,
            max_output_size=None,
        )
        return self._scratch_context.prepare_output(
            output,
            threshold=threshold,
            source="bash",
            label=command,
            project_id=self._project_id,
            session_id=self._session_id,
            agent_slug=self._agent_slug,
            working_dir=self.working_dir,
        )

    async def _bash_result(self, command: str, *, threshold: int = MAX_OUTPUT_SIZE) -> ScratchOutputResult:
        """Execute a bash command with safety checks and scratch indexing."""
        auto_detached = _rewrite_in_band_agent_hub_restart(command)
        if auto_detached:
            rewritten_command, message = auto_detached
            result = await self._run_bash_process(rewritten_command, threshold=threshold)
            content = result.content.strip()
            combined = f"{message}\n{content}" if content else message
            return ScratchOutputResult(
                content=combined,
                artifact_id=result.artifact_id,
                raw_chars=result.raw_chars,
                returned_chars=len(combined),
                saved_chars=result.saved_chars,
            )

        in_band_restart_reason = _in_band_agent_hub_restart_block_reason(command)
        if in_band_restart_reason:
            return inline_output_result(f"Error: Command blocked for runtime safety: {in_band_restart_reason}")

        self_hosting_block_reason = _self_hosting_restart_block_reason(command, self._env)
        if self_hosting_block_reason:
            return inline_output_result(f"Error: Command blocked for runtime safety: {self_hosting_block_reason}")

        if self._allowed_root and not self._is_path_allowed(self.working_dir):
            return inline_output_result("Error: Working directory outside allowed project root")

        return await self._run_bash_process(command, threshold=threshold)

    async def bash(self, command: str) -> str:
        """Execute a bash command with environment inheritance."""
        return (await self._bash_result(command)).content

    async def search_scratch_context(
        self,
        query: str = "",
        artifact_id: str | None = None,
        limit: int = 5,
        context_lines: int = 2,
    ) -> str:
        """Search scratch artifacts created by previous direct tool output."""
        return self._scratch_context.search(
            query=query,
            artifact_id=artifact_id,
            project_id=self._project_id,
            session_id=self._session_id,
            limit=limit,
            context_lines=context_lines,
        )

    async def batch_execute(self, commands: list[str] | None = None, stop_on_error: bool = True) -> str:
        """Execute a bounded list of bash commands with compact scratch-aware output."""
        if not isinstance(commands, list) or not commands:
            return "Error: batch_execute requires a non-empty commands list."
        if len(commands) > MAX_BATCH_COMMANDS:
            return f"Error: batch_execute accepts at most {MAX_BATCH_COMMANDS} commands."

        entries: list[str] = []
        total_raw = 0
        total_returned = 0
        total_saved = 0
        indexed = 0
        ran = 0

        for index, command in enumerate(commands, start=1):
            if not isinstance(command, str) or not command.strip():
                return f"Error: command {index} must be a non-empty string."
            result = await self._bash_result(command, threshold=BATCH_OUTPUT_THRESHOLD)
            ran += 1
            total_raw += result.raw_chars
            total_returned += result.returned_chars
            total_saved += result.saved_chars
            if result.artifact_id:
                indexed += 1
            status = "error" if _is_error_output(result.content) else "ok"
            artifact = f" artifact={result.artifact_id}" if result.artifact_id else ""
            entries.append(
                "\n".join(
                    [
                        (
                            f"[{index}/{len(commands)}] {status}{artifact} "
                            f"chars={result.raw_chars}->{result.returned_chars} "
                            f"command={command[:180]!r}"
                        ),
                        _clamp_inline(result.content),
                    ]
                )
            )
            if stop_on_error and status == "error":
                break

        saved_tokens = max(0, total_saved // 4)
        header = (
            f"BATCH_EXECUTE[requested={len(commands)}|ran={ran}|indexed={indexed}|"
            f"chars={total_raw}->{total_returned}|saved_tokens~={saved_tokens}]"
        )
        return header + "\n" + "\n\n".join(entries)

    async def read_file(self, path: str, offset: int = 0, limit: int = 2000) -> str:
        """Read a file with optional line offset and limit."""
        allowed_root, block_reason = await self._allowed_root_for_file_tool(path, write=False)
        if block_reason:
            return f"Error: {block_reason}"
        return await _read_file(path, self.working_dir, allowed_root, offset, limit)

    async def write_file(self, path: str, content: str, allow_large_truncate: bool = False) -> str:
        """Write a file."""
        allowed_root, permission_block = await self._allowed_root_for_file_tool(path, write=True)
        if permission_block:
            return f"Error: {permission_block}"
        block_reason = await scan_runtime_sensitive_content(
            path,
            content,
            repo_root=str(self.working_dir),
            tool_name="write_file",
        )
        if block_reason:
            return f"Error: Write blocked: {block_reason}"
        return await _write_file(
            path,
            content,
            self.working_dir,
            allowed_root,
            allow_large_truncate=allow_large_truncate,
        )

    async def edit_file(
        self,
        path: str,
        old_text: str,
        new_text: str,
        replace_all: bool = False,
    ) -> str:
        """Edit an existing file by replacing exact text."""
        allowed_root, permission_block = await self._allowed_root_for_file_tool(path, write=True)
        if permission_block:
            return f"Error: {permission_block}"

        async def _guard(updated_content: str) -> str | None:
            return await scan_runtime_sensitive_content(
                path,
                updated_content,
                repo_root=str(self.working_dir),
                tool_name="edit_file",
            )

        return await _edit_file(
            path,
            old_text,
            new_text,
            self.working_dir,
            allowed_root,
            replace_all=replace_all,
            content_guard=_guard,
        )

    async def consult_agent(self, agent_slug: str, question: str, context: str = "") -> str:
        """Consult another agent for advice without executing tools."""
        from app.services.tools._executor_consultation import consult_agent as _consult
        return await _consult(
            self._project_id,
            agent_slug,
            question,
            context,
            parent_session_id=self._session_id,
        )

    async def dispatch_agent(
        self, agent_slug: str, task: str,
        project_id: str | None = None, max_turns: int | None = None,
    ) -> str:
        """Dispatch an agent with full tool access to perform a task."""
        from app.services.tools._executor_consultation import dispatch_agent as _dispatch
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
