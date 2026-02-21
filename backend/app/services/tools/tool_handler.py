"""Tool handler implementation for direct tool execution.

Provides DirectToolHandler which routes tool calls to DirectToolExecutor
methods and handles permission checking.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.services.tools.base import PreToolUseHook, ToolCall, ToolHandler, ToolResult
from app.services.tools.direct_executor_core import DirectToolExecutor
from app.services.tools.tool_definitions import DEFAULT_TIMEOUT

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
        """Execute a tool call."""
        start = time.monotonic()
        # Normalize SDK PascalCase names to our lowercase convention
        tool_name = _SDK_TOOL_NAME_MAP.get(tool_call.name, tool_call.name)
        try:
            if tool_name == "bash":
                output = await self._executor.bash(
                    command=tool_call.input.get("command", ""),
                    timeout=tool_call.input.get("timeout", DEFAULT_TIMEOUT),
                )
            elif tool_name == "read_file":
                output = await self._executor.read_file(
                    path=tool_call.input.get("path", ""),
                    offset=tool_call.input.get("offset", 0),
                    limit=tool_call.input.get("limit", 2000),
                )
            elif tool_name == "write_file":
                output = await self._executor.write_file(
                    path=tool_call.input.get("path", ""),
                    content=tool_call.input.get("content", ""),
                )
            elif tool_name == "consult_agent":
                output = await self._executor.consult_agent(
                    agent_slug=tool_call.input.get("agent_slug", ""),
                    question=tool_call.input.get("question", ""),
                    context=tool_call.input.get("context", ""),
                )
            elif tool_name == "send_push":
                output = await self._executor.send_push(
                    title=tool_call.input.get("title", ""),
                    body=tool_call.input.get("body", ""),
                    url=tool_call.input.get("url"),
                    severity=tool_call.input.get("severity", "info"),
                    tag=tool_call.input.get("tag"),
                )
            else:
                output = f"Unknown tool: {tool_name} (original: {tool_call.name})"

            duration_ms = int((time.monotonic() - start) * 1000)
            return ToolResult(
                tool_use_id=tool_call.id,
                content=output,
                is_error=output.startswith("Error:"),
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Tool execution error: {e}",
                is_error=True,
                duration_ms=duration_ms,
            )


def create_direct_handler(
    working_dir: str | None = None,
    permission_config: dict[str, Any] | None = None,
    project_id: str | None = None,
) -> DirectToolHandler:
    """Create a direct tool handler with optional permission checking.

    Args:
        working_dir: Base directory for tool operations
        permission_config: Optional PermissionConfig as dict (mode, allow_list, etc.)
        project_id: Project ID for agent consultation (enables consult_agent tool)

    Returns:
        DirectToolHandler configured for the directory with permission hook
    """
    pre_hook: PreToolUseHook | None = None

    if permission_config:
        from app.services.tools.permissions import PermissionChecker, PermissionConfig

        config = PermissionConfig.from_dict(permission_config)
        checker = PermissionChecker(config)
        pre_hook = checker.create_hook()
        logger.info(f"Created tool handler with permission mode: {config.mode.value}")

    return DirectToolHandler(working_dir, pre_hook=pre_hook, project_id=project_id)
