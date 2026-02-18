"""Helper functions for claude_tools.py — hook building and SDK option construction."""

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal, cast

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


def _build_tool_hooks(
    after_tool_callback: Callable[[str, dict[str, Any], str, int | None], Awaitable[None]] | None,
) -> Any:
    """Build typed SDK hook matchers for pre/post tool timing and observation."""
    from claude_agent_sdk import HookMatcher
    from claude_agent_sdk.types import (
        AsyncHookJSONOutput,
        HookContext,
        PostToolUseHookInput,
        PreToolUseHookInput,
        SyncHookJSONOutput,
    )

    tool_start_times: dict[str, float] = {}

    async def pre_tool_timing_hook(
        input_data: PreToolUseHookInput | PostToolUseHookInput | Any,
        tool_use_id: str | None,
        context: HookContext,
    ) -> AsyncHookJSONOutput | SyncHookJSONOutput:
        """Record tool start time for duration calculation."""
        tool_start_times[tool_use_id or ""] = time.monotonic()
        return cast(SyncHookJSONOutput, {})

    async def post_tool_hook(
        input_data: PreToolUseHookInput | PostToolUseHookInput | Any,
        tool_use_id: str | None,
        context: HookContext,
    ) -> AsyncHookJSONOutput | SyncHookJSONOutput:
        """Invoke after_tool_callback with timing; fallback capture exists in core.py."""
        if not after_tool_callback:
            return cast(AsyncHookJSONOutput, {})
        input_dict = cast(dict[str, Any], input_data)
        tool_name = input_dict.get("tool_name", "")
        tool_input = input_dict.get("tool_input", {})
        tool_output = input_dict.get("tool_output", "")
        start = tool_start_times.pop(tool_use_id or "", None)
        duration_ms = int((time.monotonic() - start) * 1000) if start is not None else None
        try:
            await after_tool_callback(tool_name, tool_input, tool_output, duration_ms)
        except Exception as e:
            logger.warning(f"After tool callback error: {e}")
        return cast(AsyncHookJSONOutput, {})

    hooks: dict[str, list[HookMatcher]] = {}
    if after_tool_callback:
        hooks["PreToolUse"] = [HookMatcher(hooks=[pre_tool_timing_hook])]
        hooks["PostToolUse"] = [HookMatcher(hooks=[post_tool_hook])]

    return cast(
        dict[
            Literal["PreToolUse", "PostToolUse", "UserPromptSubmit", "Stop", "SubagentStop", "PreCompact"],
            list[HookMatcher],
        ],
        hooks,
    )


def _build_sdk_options(
    model: str,
    model_map: dict[str, str],
    working_dir: str | None,
    cli_path: str,
    hooks_typed: Any,
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
    if hooks_typed:
        sdk_opts["hooks"] = hooks_typed

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
