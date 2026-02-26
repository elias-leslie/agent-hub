"""Tool handling and helpers for Claude adapter — permission checking, MCP, and SDK tool execution."""

import logging
from collections.abc import AsyncIterator
from typing import Any

from app.adapters.base import Message, ProviderError
from app.adapters.claude_utils import _sdk_semaphore, build_claude_prompt, build_sdk_options

logger = logging.getLogger(__name__)

# Tools already built into Claude Code CLI — skip when building MCP server
_CLI_BUILTIN_TOOLS = frozenset({"bash", "read_file", "write_file"})

_MCP_RACE_PATCHED = False


def _patch_sdk_mcp_race_condition() -> None:
    """Patch SDK race condition where MCP control response writes fail during shutdown.

    The SDK spawns _handle_control_request as a background task (start_soon)
    but close() can cancel the task group before the response is written back,
    causing CLIConnectionError. This patch catches that specific error.
    """
    global _MCP_RACE_PATCHED
    if _MCP_RACE_PATCHED:
        return
    _MCP_RACE_PATCHED = True

    try:
        from claude_agent_sdk._errors import CLIConnectionError
        from claude_agent_sdk._internal.query import Query

        original = Query._handle_control_request

        async def _safe_handle_control_request(self: Any, request: Any) -> None:
            try:
                await original(self, request)
            except CLIConnectionError:
                logger.debug("MCP control response write failed (transport closed during shutdown)")
            except Exception:
                logger.debug("MCP control request error during shutdown", exc_info=True)

        Query._handle_control_request = _safe_handle_control_request  # type: ignore[assignment]
        logger.info("Patched SDK MCP race condition in Query._handle_control_request")
    except Exception:
        logger.warning("Failed to patch SDK MCP race condition", exc_info=True)


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


def _build_mcp_server(
    tools: list[dict[str, Any]],
    working_dir: str | None,
    project_id: str | None,
) -> Any | None:
    """Build an in-process SDK MCP server for custom tools.

    Registers non-CLI-builtin tools as MCP tools backed by DirectToolExecutor.
    Returns None if no custom tools to register.
    """
    from claude_agent_sdk import create_sdk_mcp_server
    from claude_agent_sdk import tool as sdk_tool

    from app.services.tools.direct_executor_core import DirectToolExecutor

    custom_tools = [t for t in tools if t["name"] not in _CLI_BUILTIN_TOOLS]
    if not custom_tools:
        return None

    _patch_sdk_mcp_race_condition()

    executor = DirectToolExecutor(working_dir, project_id=project_id)
    mcp_tools = []
    for t in custom_tools:
        tool_name = t["name"]

        async def handler(args: dict[str, Any], _name: str = tool_name) -> dict[str, Any]:
            try:
                result = await executor.dispatch(_name, args)
                return {"content": [{"type": "text", "text": result}]}
            except Exception as e:
                logger.exception("MCP handler error: tool=%s", _name)
                return {"content": [{"type": "text", "text": f"Error: {e}"}], "is_error": True}

        mcp_tools.append(sdk_tool(tool_name, t["description"], t["input_schema"])(handler))

    return create_sdk_mcp_server("agent-hub-tools", tools=mcp_tools)


async def _wrap_prompt_as_stream(prompt: str) -> Any:
    """Wrap a string prompt as an async iterable for SDK streaming mode."""

    async def _stream() -> Any:
        yield {
            "type": "user",
            "message": {"role": "user", "content": prompt},
            "parent_tool_use_id": None,
            "session_id": None,
        }

    return _stream()


async def _stream_sdk_messages(
    prompt: str | Any,
    options: Any,
    provider_name: str,
) -> AsyncIterator[tuple[Any, str | None]]:
    """Yield (message, session_id) pairs from claude_agent_sdk query."""
    from claude_agent_sdk import query

    session_id: str | None = None
    async with _sdk_semaphore:
        try:
            async for message in query(prompt=prompt, options=options):
                if hasattr(message, "subtype") and message.subtype == "init" and hasattr(message, "data"):
                    session_id = message.data.get("session_id")  # ty: ignore[unresolved-attribute]
                    if session_id:
                        logger.info(f"Claude SDK session ID: {session_id}")
                yield (message, session_id)
        except Exception as e:
            logger.error(f"Claude tool error: {e}")
            raise ProviderError(f"Claude tool error: {e}", provider=provider_name, retriable=True) from e


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
    **kwargs: Any,
) -> AsyncIterator[tuple[Any, str | None]]:
    """Generate with native tool calling using SDK-native permission mechanisms."""
    can_use_tool_cb = _build_can_use_tool(permission_checker) if permission_checker and not yolo_mode else None
    mcp_server = _build_mcp_server(tools, working_dir, kwargs.get("project_id")) if tools else None
    mcp_servers = {"agent-hub": mcp_server} if mcp_server else None

    options, use_streaming_prompt = build_sdk_options(
        cli_path=cli_path,
        model=model,
        model_map=model_map,
        working_dir=working_dir,
        yolo_mode=yolo_mode,
        can_use_tool=can_use_tool_cb,
        mcp_servers=mcp_servers,
        resume_session_id=resume_session_id,
    )
    full_prompt = build_claude_prompt(messages)
    prompt: str | Any = await _wrap_prompt_as_stream(full_prompt) if use_streaming_prompt else full_prompt
    async for item in _stream_sdk_messages(prompt, options, provider_name):
        yield item
