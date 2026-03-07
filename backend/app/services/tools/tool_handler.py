"""Tool handler implementation for direct tool execution.

Provides DirectToolHandler which routes tool calls to DirectToolExecutor
methods and handles permission checking, including project-level
permission tier enforcement.
"""

from __future__ import annotations

import logging
import time

from app.services.tools._cross_project_hook import (
    create_cross_project_permission_hook as _create_cross_project_permission_hook,
)
from app.services.tools.base import (
    PreToolUseHook,
    ToolCall,
    ToolDecision,
    ToolHandler,
    ToolResult,
)
from app.services.tools.direct_executor_core import DirectToolExecutor

logger = logging.getLogger(__name__)

# Claude Agent SDK uses PascalCase tool names (Bash, Read, Write, Edit)
# but our handler uses lowercase names. Normalize before routing.
_SDK_TOOL_NAME_MAP: dict[str, str] = {
    "Bash": "bash",
    "Read": "read_file",
    "Write": "write_file",
    "Edit": "write_file",
}

# Tools that require audit logging due to security sensitivity.
# Maps tool name → sensitivity level for filtering/alerting.
SENSITIVE_TOOLS: dict[str, str] = {
    "bash": "high",        # Arbitrary command execution
    "write_file": "high",  # File system modification
    "send_push": "medium", # External communication
}


class DirectToolHandler(ToolHandler):
    """Tool handler that uses direct executor."""

    def __init__(
        self,
        working_dir: str | None = None,
        pre_hook: PreToolUseHook | None = None,
        project_id: str | None = None,
        session_id: str | None = None,
        tool_catalog: list[dict[str, object]] | None = None,
    ):
        """Initialize with working directory and optional permission hook.

        Args:
            working_dir: Base directory for all operations
            pre_hook: Optional async callback for permission checking
            project_id: Project ID for agent consultation (enables consult_agent)
        """
        super().__init__(pre_hook=pre_hook)
        self._executor = DirectToolExecutor(
            working_dir,
            project_id=project_id,
            session_id=session_id,
            tool_catalog=tool_catalog,
        )

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call with permission checking."""
        start = time.monotonic()
        tool_name = _SDK_TOOL_NAME_MAP.get(tool_call.name, tool_call.name)

        if tool_name == "tool_catalog":
            return await self._execute_catalog_tool(tool_call, start)

        normalized_call = ToolCall(
            id=tool_call.id, name=tool_name, input=tool_call.input,
            caller=tool_call.caller, original_id=tool_call.original_id,
        )

        # Fail-closed: any exception during permission checking denies access.
        try:
            decision = await self.check_permission(normalized_call)
        except Exception as e:
            logger.error("Permission check error for tool '%s': %s — denying", tool_name, e)
            decision = ToolDecision.DENY

        if decision == ToolDecision.DENY:
            duration_ms = int((time.monotonic() - start) * 1000)
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Error: Tool '{tool_name}' denied by permission policy",
                is_error=True,
                duration_ms=duration_ms,
            )

        try:
            output = await self._executor.dispatch(tool_name, tool_call.input)
        except Exception as e:
            output = f"Tool execution error: {e}"

        duration_ms = int((time.monotonic() - start) * 1000)
        return ToolResult(
            tool_use_id=tool_call.id,
            content=output,
            is_error=output.startswith("Error:") or output.startswith("Unknown tool:"),
            duration_ms=duration_ms,
        )

    async def _execute_catalog_tool(self, tool_call: ToolCall, start: float) -> ToolResult:
        """Execute a discovered catalog tool without bypassing its permission checks."""
        target_name = _SDK_TOOL_NAME_MAP.get(
            str(tool_call.input.get("tool_name", "")),
            str(tool_call.input.get("tool_name", "")),
        )
        target_args = tool_call.input.get("arguments", {})
        nested_call = ToolCall(
            id=tool_call.id,
            name=target_name,
            input=target_args if isinstance(target_args, dict) else {},
            caller=tool_call.caller,
            original_id=tool_call.original_id,
        )

        if not self._executor.has_catalog_tool(target_name):
            duration_ms = int((time.monotonic() - start) * 1000)
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Error: Unknown catalog tool '{target_name}'",
                is_error=True,
                duration_ms=duration_ms,
            )

        try:
            decision = await self.check_permission(nested_call)
        except Exception as e:
            logger.error("Permission check error for catalog tool '%s': %s — denying", target_name, e)
            decision = ToolDecision.DENY

        if decision == ToolDecision.DENY:
            duration_ms = int((time.monotonic() - start) * 1000)
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Error: Tool '{target_name}' denied by permission policy",
                is_error=True,
                duration_ms=duration_ms,
            )

        try:
            output = await self._executor.dispatch(target_name, nested_call.input)
        except Exception as e:
            output = f"Tool execution error: {e}"

        duration_ms = int((time.monotonic() - start) * 1000)
        return ToolResult(
            tool_use_id=tool_call.id,
            content=output,
            is_error=output.startswith("Error:") or output.startswith("Unknown tool:"),
            duration_ms=duration_ms,
        )


def _compose_hooks(hooks: list[PreToolUseHook]) -> PreToolUseHook:
    """Compose multiple pre-hooks. First DENY wins.

    Fail-closed: any exception from a hook results in DENY.
    """

    async def _composed(tool_call: ToolCall) -> ToolDecision:
        try:
            for hook in hooks:
                decision = await hook(tool_call)
                if decision == ToolDecision.DENY:
                    return ToolDecision.DENY
            return ToolDecision.ALLOW
        except Exception as e:
            logger.error("Composed hook error for %s: %s — denying", tool_call.name, e)
            return ToolDecision.DENY

    return _composed


def _create_project_permission_hook(project_id: str) -> PreToolUseHook:
    """Create a pre-hook that checks project permission tier.

    Fail-closed: any exception during permission checking results in DENY.
    """

    async def _hook(tool_call: ToolCall) -> ToolDecision:
        try:
            from app.services.project_permission_service import check_tool_allowed

            allowed, reason = await check_tool_allowed(project_id, tool_call.name)
            if not allowed:
                logger.info(
                    "Project permission DENY: %s for %s (%s)",
                    tool_call.name, project_id, reason,
                )
                return ToolDecision.DENY
            return ToolDecision.ALLOW
        except Exception as e:
            logger.error(
                "Project permission hook error for %s/%s: %s — denying",
                project_id, tool_call.name, e,
            )
            return ToolDecision.DENY

    return _hook


def create_direct_handler(
    working_dir: str | None = None,
    permission_config: dict[str, str | list[str]] | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    tool_catalog: list[dict[str, object]] | None = None,
) -> DirectToolHandler:
    """Create a direct tool handler with optional permission checking.

    Composes hooks in order: project permission first, then cross-project
    path enforcement, then config-based permission. First DENY wins.

    Args:
        working_dir: Base directory for tool operations
        permission_config: Optional PermissionConfig as dict (mode, allow_list, etc.)
        project_id: Project ID for agent consultation (enables consult_agent tool)

    Returns:
        DirectToolHandler configured for the directory with permission hook
    """
    hooks: list[PreToolUseHook] = []

    if project_id:
        hooks.append(_create_project_permission_hook(project_id))
        hooks.append(_create_cross_project_permission_hook(project_id))

    if working_dir:
        from app.services.tools._worktree_boundary_hook import create_worktree_boundary_hook

        hooks.append(create_worktree_boundary_hook(working_dir))

    if permission_config:
        from app.services.tools.permissions import PermissionChecker, PermissionConfig

        config = PermissionConfig.from_dict(permission_config)
        checker = PermissionChecker(config)
        hooks.append(checker.create_hook())
        logger.info(f"Created tool handler with permission mode: {config.mode.value}")

    pre_hook: PreToolUseHook | None = None
    if len(hooks) == 1:
        pre_hook = hooks[0]
    elif len(hooks) > 1:
        pre_hook = _compose_hooks(hooks)

    return DirectToolHandler(
        working_dir,
        pre_hook=pre_hook,
        project_id=project_id,
        session_id=session_id,
        tool_catalog=tool_catalog,
    )
