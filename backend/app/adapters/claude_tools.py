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
        """PreToolUse hook for permission control."""
        # Cast to dict to access fields
        input_dict = cast(dict[str, Any], input_data)
        tool_name = input_dict.get("tool_name", "")
        tool_input = input_dict.get("tool_input", {})
        hook_event_name = input_dict.get("hook_event_name", "PreToolUse")

        # Read tools always allowed
        if tool_name in READ_TOOLS:
            return cast(
                AsyncHookJSONOutput,
                {
                    "hookSpecificOutput": {
                        "hookEventName": hook_event_name,
                        "permissionDecision": "allow",
                    }
                },
            )

        # Write tools need permission
        if tool_name in WRITE_TOOLS:
            if not write_enabled:
                return cast(
                    AsyncHookJSONOutput,
                    {
                        "hookSpecificOutput": {
                            "hookEventName": hook_event_name,
                            "permissionDecision": "deny",
                            "permissionDecisionReason": "Write access not enabled",
                        }
                    },
                )

            if yolo_mode:
                return cast(
                    AsyncHookJSONOutput,
                    {
                        "hookSpecificOutput": {
                            "hookEventName": hook_event_name,
                            "permissionDecision": "allow",
                        }
                    },
                )

            # Use permission callback if available
            if permission_callback:
                try:
                    approved = await permission_callback(tool_name, tool_input)
                    decision = "allow" if approved else "deny"
                    result: dict[str, Any] = {
                        "hookSpecificOutput": {
                            "hookEventName": hook_event_name,
                            "permissionDecision": decision,
                        }
                    }
                    if not approved:
                        result["hookSpecificOutput"]["permissionDecisionReason"] = (
                            "Permission denied by user"
                        )
                    return cast(AsyncHookJSONOutput, result)
                except Exception as e:
                    logger.error(f"Permission callback error: {e}")
                    return cast(
                        AsyncHookJSONOutput,
                        {
                            "hookSpecificOutput": {
                                "hookEventName": hook_event_name,
                                "permissionDecision": "deny",
                                "permissionDecisionReason": f"Permission callback error: {e}",
                            }
                        },
                    )

            # No callback - deny for safety
            return cast(
                AsyncHookJSONOutput,
                {
                    "hookSpecificOutput": {
                        "hookEventName": hook_event_name,
                        "permissionDecision": "deny",
                        "permissionDecisionReason": "Permission required but no callback",
                    }
                },
            )

        # Unknown tools - allow
        return cast(AsyncHookJSONOutput, {})

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
