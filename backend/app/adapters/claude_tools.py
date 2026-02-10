"""Tool handling with hooks for Claude adapter."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Literal, cast

from app.adapters.base import Message, ProviderError

logger = logging.getLogger(__name__)


def _build_can_use_tool(
    checker: Any,
) -> Any:
    """Build a can_use_tool callback that maps PermissionChecker decisions to SDK types.

    Args:
        checker: PermissionChecker instance from app.services.tools.permissions

    Returns:
        Async callback compatible with ClaudeAgentOptions.can_use_tool
    """
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


async def _wrap_prompt_as_stream(prompt: str) -> Any:
    """Wrap a string prompt as an async iterable for SDK streaming mode.

    Required when using can_use_tool callback, which needs streaming mode.
    """

    async def _stream():
        yield {
            "type": "user",
            "message": {"role": "user", "content": prompt},
            "parent_tool_use_id": None,
            "session_id": None,
        }

    return _stream()


async def complete_with_tools(
    messages: list[Message],
    model: str,
    tools: list[dict[str, Any]],
    yolo_mode: bool,
    permission_checker: Any | None,
    working_dir: str | None,
    resume_session_id: str | None,
    cli_path: str,
    model_map: dict[str, str],
    provider_name: str,
    after_tool_callback: Callable[[str, dict[str, Any], str], Awaitable[None]] | None,
    **kwargs: Any,
) -> AsyncIterator[tuple[Any, str | None]]:
    """Generate with native tool calling using SDK-native permission mechanisms.

    Args:
        messages: Conversation messages
        model: Model identifier
        tools: Tool definitions in Anthropic API format
        yolo_mode: Auto-approve all tools via bypassPermissions mode
        permission_checker: PermissionChecker instance for granular/ask modes (None = yolo)
        working_dir: Working directory for agent
        resume_session_id: SDK session ID to resume (for continuation)
        cli_path: Path to Claude CLI
        model_map: Model name mapping
        provider_name: Provider name for errors
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

    # Build hooks — only PostToolUse for observation (permissions handled by SDK)
    hooks: dict[str, list[HookMatcher]] = {}
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

    # Build SDK options
    sdk_opts: dict[str, Any] = {
        "cwd": working_dir or ".",
        "cli_path": cli_path,
        "model": sdk_model,
    }

    # Only include hooks if we have any
    if hooks_typed:
        sdk_opts["hooks"] = hooks_typed

    # Permission handling via SDK-native mechanisms
    use_streaming_prompt = False
    if yolo_mode:
        sdk_opts["permission_mode"] = "bypassPermissions"
    elif permission_checker:
        sdk_opts["can_use_tool"] = _build_can_use_tool(permission_checker)
        use_streaming_prompt = True  # can_use_tool requires streaming mode

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

    # When using can_use_tool, prompt must be an AsyncIterable (streaming mode)
    prompt: str | Any
    if use_streaming_prompt:
        prompt = await _wrap_prompt_as_stream(full_prompt)
    else:
        prompt = full_prompt

    session_id: str | None = None
    try:
        async for message in query(prompt=prompt, options=options):
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
