"""Helper functions for claude_tools.py — permission checking and SDK option construction."""

import logging
from typing import Any

from app.services.tools.project_env import build_venv_env_overlay

logger = logging.getLogger(__name__)


def _build_can_use_tool(checker: Any) -> Any:
    """Build a can_use_tool callback mapping PermissionChecker decisions to SDK types."""
    from claude_agent_sdk.types import (
        PermissionResultAllow,
        PermissionResultDeny,
        ToolPermissionContext,
    )

    from app.services.tools.base import ToolCall, ToolDecision

    async def can_use_tool(
        tool_name: str,
        tool_input: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        tool_call = ToolCall(id="", name=tool_name, input=tool_input)
        decision = await checker.check(tool_call)
        if decision == ToolDecision.ALLOW:
            return PermissionResultAllow()
        elif decision == ToolDecision.DENY:
            return PermissionResultDeny(
                message=f"Tool '{tool_name}' denied by permission config"
            )
        else:  # ASK — deny in autonomous mode (no user to confirm)
            return PermissionResultDeny(
                message=f"Tool '{tool_name}' requires confirmation (autonomous mode)"
            )

    return can_use_tool


def _build_sdk_options(
    model: str,
    model_map: dict[str, str],
    working_dir: str | None,
    cli_path: str,
    yolo_mode: bool,
    permission_checker: Any | None,
    resume_session_id: str | None,
) -> tuple[Any, bool]:
    """Build ClaudeAgentOptions; return (options, use_streaming_prompt)."""
    from claude_agent_sdk import ClaudeAgentOptions

    sdk_model = model_map.get(model, model)
    sdk_opts: dict[str, Any] = {
        "cwd": working_dir or ".",
        "cli_path": cli_path,
        "model": sdk_model,
        "env": build_venv_env_overlay(working_dir or "."),
    }

    use_streaming_prompt = False
    if yolo_mode:
        sdk_opts["permission_mode"] = "bypassPermissions"
    elif permission_checker:
        sdk_opts["can_use_tool"] = _build_can_use_tool(permission_checker)
        use_streaming_prompt = True  # can_use_tool requires streaming mode

    if resume_session_id:
        sdk_opts["resume"] = resume_session_id
        logger.info(f"Claude SDK resuming session: {resume_session_id}")

    return ClaudeAgentOptions(**sdk_opts), use_streaming_prompt
