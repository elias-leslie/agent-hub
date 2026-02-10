"""Tool handling with hooks for Claude adapter."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Literal, cast

from app.adapters.base import Message, ProviderError
from app.adapters.claude_utils import READ_TOOLS, WRITE_TOOLS

logger = logging.getLogger(__name__)


async def complete_with_tools(
    messages: list[Message],
    model: str,
    tools: list[dict[str, Any]],
    write_enabled: bool,
    yolo_mode: bool,
    working_dir: str | None,
    resume_session_id: str | None,
    cli_path: str,
    model_map: dict[str, str],
    provider_name: str,
    permission_callback: Callable[[str, dict[str, Any]], Awaitable[bool]] | None,
    after_tool_callback: Callable[[str, dict[str, Any], str], Awaitable[None]] | None,
    **kwargs: Any,
) -> AsyncIterator[tuple[Any, str | None]]:
    """Generate with native tool calling using PreToolUse/PostToolUse hooks.

    Args:
        messages: Conversation messages
        model: Model identifier
        tools: Tool definitions in Anthropic API format
        write_enabled: Whether write tools are enabled
        yolo_mode: Auto-approve all write tool requests
        working_dir: Working directory for agent
        resume_session_id: SDK session ID to resume (for continuation)
        cli_path: Path to Claude CLI
        model_map: Model name mapping
        provider_name: Provider name for errors
        permission_callback: Async callback for tool permission prompts
        after_tool_callback: Async callback after tool execution
        **kwargs: Additional parameters

    Yields:
        Tuple of (SDK message object, session_id).
        session_id is populated from init and included with each yield.
    """

    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, query
    from claude_agent_sdk.types import (
        AsyncHookJSONOutput,
        HookContext,
        PostToolUseHookInput,
        PreToolUseHookInput,
        SyncHookJSONOutput,
    )

    async def permission_hook(
        input_data: PreToolUseHookInput | PostToolUseHookInput | Any,
        tool_use_id: str | None,
        context: HookContext,
    ) -> AsyncHookJSONOutput | SyncHookJSONOutput:
        """PreToolUse hook for permission control.

        Handles both Agent Hub custom tools (read_file, write_file, etc.)
        and Claude Code native tools (Bash, Read, Write, Edit, Glob, Grep).
        Must return explicit "allow" for all tools in yolo_mode — returning
        an empty dict lets Claude Code's internal permission system take over,
        which requires user approval for Bash commands.
        """
        # Cast to dict to access fields
        input_dict = cast(dict[str, Any], input_data)
        tool_name = input_dict.get("tool_name", "")
        tool_input = input_dict.get("tool_input", {})
        hook_event_name = input_dict.get("hook_event_name", "PreToolUse")

        def _allow() -> AsyncHookJSONOutput:
            return cast(
                AsyncHookJSONOutput,
                {
                    "hookSpecificOutput": {
                        "hookEventName": hook_event_name,
                        "permissionDecision": "allow",
                    }
                },
            )

        def _deny(reason: str) -> AsyncHookJSONOutput:
            return cast(
                AsyncHookJSONOutput,
                {
                    "hookSpecificOutput": {
                        "hookEventName": hook_event_name,
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                    }
                },
            )

        # Yolo mode: allow ALL tools (both custom and Claude Code native)
        if yolo_mode:
            return _allow()

        # Read tools always allowed (custom + Claude Code native)
        _read_tools = READ_TOOLS | {"Read", "Glob", "Grep", "WebFetch", "WebSearch"}
        if tool_name in _read_tools:
            return _allow()

        # Write tools need permission (custom + Claude Code native)
        _write_tools = WRITE_TOOLS | {"Write", "Edit", "Bash", "NotebookEdit", "Task"}
        if tool_name in _write_tools:
            if not write_enabled:
                return _deny("Write access not enabled")

            # Use permission callback if available
            if permission_callback:
                try:
                    approved = await permission_callback(tool_name, tool_input)
                    if approved:
                        return _allow()
                    return _deny("Permission denied by user")
                except Exception as e:
                    logger.error(f"Permission callback error: {e}")
                    return _deny(f"Permission callback error: {e}")

            # No callback - deny for safety
            return _deny("Permission required but no callback")

        # Unknown tools - allow (explicit decision to prevent Claude Code fallback)
        return _allow()

    async def post_tool_hook(
        input_data: PreToolUseHookInput | PostToolUseHookInput | Any,
        tool_use_id: str | None,
        context: HookContext,
    ) -> AsyncHookJSONOutput | SyncHookJSONOutput:
        """PostToolUse hook for observation capture.

        NOTE: This hook may not be called by all Claude SDK configurations.
        Tool results are captured via ToolUseBlock processing in core.py as a fallback.
        """
        if not after_tool_callback:
            return cast(AsyncHookJSONOutput, {})

        # Cast to dict to access fields
        input_dict = cast(dict[str, Any], input_data)
        tool_name = input_dict.get("tool_name", "")
        tool_input = input_dict.get("tool_input", {})
        tool_output = input_dict.get("tool_output", "")

        try:
            await after_tool_callback(tool_name, tool_input, tool_output)
        except Exception as e:
            logger.warning(f"After tool callback error: {e}")

        return cast(AsyncHookJSONOutput, {})

    # Build hooks
    hooks: dict[str, list[HookMatcher]] = {"PreToolUse": [HookMatcher(hooks=[permission_hook])]}
    if after_tool_callback:
        hooks["PostToolUse"] = [HookMatcher(hooks=[post_tool_hook])]

    # Map model to SDK name
    sdk_model = model_map.get(model, model)

    hooks_typed = cast(
        dict[
            Literal[
                "PreToolUse",
                "PostToolUse",
                "UserPromptSubmit",
                "Stop",
                "SubagentStop",
                "PreCompact",
            ],
            list[HookMatcher],
        ],
        hooks,
    )

    # Build SDK options with optional session resume
    sdk_opts: dict[str, Any] = {
        "cwd": working_dir or ".",
        "cli_path": cli_path,
        "model": sdk_model,
        "hooks": hooks_typed,
    }
    if resume_session_id:
        sdk_opts["resume"] = resume_session_id
        logger.info(f"Claude SDK resuming session: {resume_session_id}")

    options = ClaudeAgentOptions(**sdk_opts)

    # Build prompt from messages
    system_parts: list[str] = []
    prompt_parts: list[str] = []
    for msg_item in messages:
        content_str = (
            msg_item.content if isinstance(msg_item.content, str) else str(msg_item.content)
        )
        if msg_item.role == "system":
            system_parts.append(content_str)
        elif msg_item.role == "user":
            prompt_parts.append(content_str)

    full_prompt = "\n".join(system_parts + prompt_parts)

    session_id: str | None = None
    try:
        async for message in query(prompt=full_prompt, options=options):
            # Capture session ID from init
            if (
                hasattr(message, "subtype")
                and message.subtype == "init"
                and hasattr(message, "data")
            ):
                session_id = message.data.get("session_id")
                if session_id:
                    logger.info(f"Claude SDK session ID: {session_id}")

            yield (message, session_id)

    except Exception as e:
        logger.error(f"Claude tool error: {e}")
        raise ProviderError(
            f"Claude tool error: {e}",
            provider=provider_name,
            retriable=True,
        ) from e
