"""Tool handler implementation for direct tool execution.

Provides DirectToolHandler which routes tool calls to DirectToolExecutor
methods and handles permission checking, including project-level
permission tier enforcement.
"""

from __future__ import annotations

import logging
import time
from typing import Any

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
    "bash": "high",      # Arbitrary command execution
    "write_file": "high",  # File system modification
    "send_push": "medium",  # External communication
}


class DirectToolHandler(ToolHandler):
    """Tool handler that uses direct executor."""

    def __init__(
        self,
        working_dir: str | None = None,
        pre_hook: PreToolUseHook | None = None,
        project_id: str | None = None,
    ):
        """Initialize with working directory and optional permission hook.

        Args:
            working_dir: Base directory for all operations
            pre_hook: Optional async callback for permission checking
            project_id: Project ID for agent consultation (enables consult_agent)
        """
        super().__init__(pre_hook=pre_hook)
        self._executor = DirectToolExecutor(working_dir, project_id=project_id)

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call with permission checking."""
        start = time.monotonic()
        # Normalize SDK PascalCase names to our lowercase convention
        tool_name = _SDK_TOOL_NAME_MAP.get(tool_call.name, tool_call.name)

        # Check permission before execution (project tier + config hooks)
        # Fail-closed: any exception during permission checking denies access.
        normalized_call = ToolCall(
            id=tool_call.id, name=tool_name, input=tool_call.input,
            caller=tool_call.caller, original_id=tool_call.original_id,
        )
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
            # Fail-closed: deny on any unexpected error
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
                logger.info("Project permission DENY: %s for %s (%s)", tool_call.name, project_id, reason)
                return ToolDecision.DENY
            return ToolDecision.ALLOW
        except Exception as e:
            # Fail-closed: deny on any unexpected error
            logger.error(
                "Project permission hook error for %s/%s: %s — denying",
                project_id, tool_call.name, e,
            )
            return ToolDecision.DENY

    return _hook


def _create_cross_project_permission_hook(session_project_id: str) -> PreToolUseHook:
    """Create a pre-hook that enforces cross-project file access permissions.

    When a session runs under one project (e.g. persona-sandbox) but accesses
    files in another project's directory, this hook checks the *target*
    project's permission tier and enforces read/write/deny accordingly.

    For bash: scans the command string for absolute paths matching known
    project roots. Not bulletproof against adversarial evasion, but catches
    all non-adversarial cross-project access (the intended threat model).

    Enforcement matrix for cross-project access:
        off  → DENY all (read_file, write_file, bash)
        read → ALLOW read_file, DENY write_file, DENY bash
        write/yolo → ALLOW all
    """
    from pathlib import Path

    from app.services.tools.direct_executor_core import KNOWN_ROOTS

    async def _hook(tool_call: ToolCall) -> ToolDecision:
        try:
            # --- File tools: hard gate on path parameter ---
            if tool_call.name in ("read_file", "write_file"):
                path = tool_call.input.get("path", "")
                if not path:
                    return ToolDecision.ALLOW

                resolved = str(Path(path).resolve())

                # Reverse-lookup: which project owns this path?
                target_project = None
                for proj_id, root in KNOWN_ROOTS.items():
                    if resolved.startswith(root):
                        target_project = proj_id
                        break

                # Path not in any known project → allow (sandbox, /tmp, etc.)
                if target_project is None:
                    return ToolDecision.ALLOW

                # Same project as session → already checked by session hook
                if target_project == session_project_id:
                    return ToolDecision.ALLOW

                # Cross-project: check target's tier
                from app.services.project_permission_service import (
                    _get_cached_tier,
                    get_project_permission,
                )

                tier = await _get_cached_tier(target_project)
                if tier is None:
                    from app.db import async_session

                    async with async_session() as db:
                        perm = await get_project_permission(db, target_project)
                    tier = perm.permission_tier if perm else None

                if tier is None or tier == "off":
                    logger.info(
                        "Cross-project DENY: %s on %s (target=%s, tier=%s)",
                        tool_call.name, path, target_project, tier,
                    )
                    return ToolDecision.DENY

                if tool_call.name == "write_file" and tier == "read":
                    logger.info(
                        "Cross-project DENY: write_file on %s (target=%s, tier=read)",
                        path, target_project,
                    )
                    return ToolDecision.DENY

                return ToolDecision.ALLOW

            # --- Bash: best-effort command string scan ---
            if tool_call.name == "bash":
                command = tool_call.input.get("command", "")
                if not command:
                    return ToolDecision.ALLOW

                from app.services.project_permission_service import (
                    _get_cached_tier,
                    get_project_permission,
                )

                for proj_id, root in KNOWN_ROOTS.items():
                    if proj_id == session_project_id:
                        continue
                    if root not in command:
                        continue

                    # Command references a cross-project path
                    tier = await _get_cached_tier(proj_id)
                    if tier is None:
                        from app.db import async_session

                        async with async_session() as db:
                            perm = await get_project_permission(db, proj_id)
                        tier = perm.permission_tier if perm else None

                    if tier in (None, "off", "read"):
                        logger.info(
                            "Cross-project DENY: bash referencing %s (target=%s, tier=%s). "
                            "Use read_file/write_file for enforced cross-project access.",
                            root, proj_id, tier,
                        )
                        return ToolDecision.DENY

                return ToolDecision.ALLOW

            # Non-file, non-bash tools: not path-gated
            return ToolDecision.ALLOW

        except Exception as e:
            logger.error(
                "Cross-project hook error for %s: %s — denying",
                tool_call.name, e,
            )
            return ToolDecision.DENY

    return _hook


def create_direct_handler(
    working_dir: str | None = None,
    permission_config: dict[str, Any] | None = None,
    project_id: str | None = None,
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

    # Project permission hook (tier-based) — checked first
    if project_id:
        hooks.append(_create_project_permission_hook(project_id))

    # Cross-project path enforcement — checked second
    if project_id:
        hooks.append(_create_cross_project_permission_hook(project_id))

    # Existing per-request permission config hook
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

    return DirectToolHandler(working_dir, pre_hook=pre_hook, project_id=project_id)
