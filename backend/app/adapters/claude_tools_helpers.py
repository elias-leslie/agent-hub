"""Tool handling and helpers for Claude adapter — permission checking, MCP, and SDK tool execution."""

import logging
from typing import Any

from app.adapters.base import Message
from app.adapters.claude_tools_mcp import build_mcp_server as _build_mcp_server_impl
from app.adapters.claude_tools_permissions import (
    compose_permission_hooks as _compose_permission_hooks,
)
from app.adapters.claude_tools_permissions import (
    make_can_use_tool_callback as _make_can_use_tool_callback,
)
from app.adapters.claude_tools_permissions import (
    normalize_tool_name as _normalize_tool_name_impl,
)
from app.adapters.claude_tools_query_session import (
    _ClaudeInternalQuerySession,
    _ClaudeSDKQuerySession,
    _close_internal_query,
    _sdk_query_via_internal_api,
    _wrap_prompt_as_stream,
)
from app.adapters.claude_tools_stream import (
    ErrorMessage,
    ResultMessage,
    _ClaudeSDKMessageStreamSession,
    _iterate_sdk_messages,
    _run_sdk_stream_loop,
    _stream_sdk_session_messages,
)
from app.adapters.claude_utils import (
    _sdk_semaphore,
    build_sdk_options,
    extract_system_and_conversation,
)
from app.adapters.runtime_session import StreamBackedRuntimeSession

logger = logging.getLogger(__name__)

# Re-export constants callers may reference
_CLI_BUILTIN_TOOLS = frozenset({"bash", "read_file", "write_file"})
_SDK_TOOL_NAME_MAP: dict[str, str] = {
    "Bash": "bash",
    "Read": "read_file",
    "Write": "write_file",
    "Edit": "write_file",
}

_STREAM_STOP = object()  # Sentinel: async iteration exhausted

# Re-exports for test and caller compatibility
__all__ = [
    "ErrorMessage",
    "ResultMessage",
    "_ClaudeInternalQuerySession",
    "_ClaudeSDKMessageStreamSession",
    "_ClaudeSDKQuerySession",
    "_close_internal_query",
    "_iterate_sdk_messages",
    "_sdk_query_via_internal_api",
    "_wrap_prompt_as_stream",
]


async def _stream_sdk_messages(
    prompt: str | Any,
    options: Any,
    provider_name: str,
) -> Any:
    """Yield (message, session_id) pairs from claude_agent_sdk query.

    Iterates the SDK directly in the calling task to preserve anyio's
    task-local cancel-scope tracking.  The previous producer-task + queue
    pattern broke this invariant, causing ``CancelScope._deliver_cancellation``
    to spin at 100 % CPU when the stream was cancelled.
    """
    async with _sdk_semaphore:
        run_loop = _run_sdk_stream_loop(_iterate_sdk_messages(prompt, options, provider_name))
        try:
            async for item in run_loop:
                yield item
        finally:
            await run_loop.aclose()


def _normalize_tool_name(name: str) -> str:
    """Normalize SDK tool names for permission hooks."""
    return _normalize_tool_name_impl(name)


def _build_can_use_tool(
    project_id: str | None = None,
    agent_slug: str | None = None,
) -> Any:
    """Build a can_use_tool callback with real runtime permission layers.

    Composes hooks in order:
      1. Project permission tier (off/read/full)
      2. Cross-project path enforcement

    Checkout boundary enforcement is handled separately via settings-based
    enforcement in ``_claude_settings.py`` (evaluated inside the subprocess).

    MCP tool names are normalized before passing to hooks since the SDK
    prepends 'mcp__<server>__' but hooks expect bare tool names.
    """
    return _make_can_use_tool_callback(
        _compose_permission_hooks(project_id),
        agent_slug=agent_slug,
    )


def _build_mcp_server(
    tools: list[dict[str, Any]],
    working_dir: str | None,
    project_id: str | None,
    agent_slug: str | None,
    tool_catalog: list[dict[str, Any]] | None,
) -> Any | None:
    """Build an in-process SDK MCP server for custom tools."""
    return _build_mcp_server_impl(
        tools,
        working_dir,
        project_id,
        agent_slug,
        tool_catalog=tool_catalog,
    )


def _resolve_can_use_tool(
    project_id: str | None,
    agent_slug: str | None,
) -> Any | None:
    """Return can_use_tool callback when permission hooks are needed, else None."""
    if project_id is None and agent_slug != "persona":
        return None
    return _build_can_use_tool(
        project_id=project_id,
        agent_slug=agent_slug,
    )


def _build_tool_infra(
    tools: list[dict[str, Any]],
    working_dir: str | None,
    project_id: str | None,
    agent_slug: str | None,
    tool_catalog: list[dict[str, Any]] | None,
) -> tuple[Any | None, dict[str, Any] | None, list[str] | None]:
    """Build can_use_tool callback, MCP servers dict, and allowed_tools list."""
    # Boundary enforcement for Claude SDK is handled via settings-based
    # enforcement (settings + PreToolUse hook) — see _claude_settings.py.
    # The can_use_tool callback here is only for non-boundary permission
    # hooks (project tier, cross-project, persona workflow policy) since the SDK subprocess
    # does not invoke can_use_tool for built-in tools.
    can_use_tool_cb = _resolve_can_use_tool(project_id, agent_slug)
    mcp_server = _build_mcp_server(tools, working_dir, project_id, agent_slug, tool_catalog) if tools else None
    mcp_servers = {"agent-hub": mcp_server} if mcp_server else None

    from app.adapters._claude_constants import build_allowed_tools

    allowed_tools = build_allowed_tools(tools) if tools else None
    return can_use_tool_cb, mcp_servers, allowed_tools


async def _build_tool_message_session(
    messages: list[Message],
    model: str,
    tools: list[dict[str, Any]],
    working_dir: str | None,
    resume_session_id: str | None,
    cli_path: str,
    model_map: dict[str, str],
    provider_name: str,
    max_turns: int | None = None,
    **kwargs: Any,
) -> _ClaudeSDKMessageStreamSession:
    """Build the owned Claude SDK message session for one tool turn."""
    project_id = kwargs.get("project_id")
    agent_slug = kwargs.get("agent_slug")
    session_id = kwargs.get("session_id")
    tool_catalog = kwargs.get("tool_catalog")

    can_use_tool_cb, mcp_servers, allowed_tools = _build_tool_infra(
        tools, working_dir, project_id, agent_slug, tool_catalog,
    )
    system_prompt, conversation_prompt = extract_system_and_conversation(messages)
    options, use_streaming_prompt = build_sdk_options(
        cli_path=cli_path,
        model=model,
        model_map=model_map,
        working_dir=working_dir,
        session_id=session_id if isinstance(session_id, str) else None,
        yolo_mode=can_use_tool_cb is None,
        can_use_tool=can_use_tool_cb,
        mcp_servers=mcp_servers,
        resume_session_id=resume_session_id,
        max_turns=max_turns,
        system_prompt=system_prompt,
        allowed_tools=allowed_tools,
        agent_slug=agent_slug,
    )
    prompt: str | Any = (
        await _wrap_prompt_as_stream(conversation_prompt)
        if use_streaming_prompt
        else conversation_prompt
    )
    del provider_name
    return _ClaudeSDKMessageStreamSession(prompt=prompt, options=options)


async def build_tool_runtime_session(
    messages: list[Message],
    model: str,
    tools: list[dict[str, Any]],
    working_dir: str | None,
    resume_session_id: str | None,
    cli_path: str,
    model_map: dict[str, str],
    provider_name: str,
    max_turns: int | None = None,
    **kwargs: Any,
) -> StreamBackedRuntimeSession:
    """Build an owned Claude runtime session with canonical ToolEvents."""
    from app.adapters.claude_tool_events import adapt_claude_stream

    sdk_session = await _build_tool_message_session(
        messages=messages,
        model=model,
        tools=tools,
        working_dir=working_dir,
        resume_session_id=resume_session_id,
        cli_path=cli_path,
        model_map=model_map,
        provider_name=provider_name,
        max_turns=max_turns,
        **kwargs,
    )
    return StreamBackedRuntimeSession(
        stream=adapt_claude_stream(
            _stream_sdk_session_messages(sdk_session, provider_name),
        ),
        interrupt_callback=sdk_session.interrupt,
        close_callback=sdk_session.close,
    )


async def complete_with_tools(
    messages: list[Message],
    model: str,
    tools: list[dict[str, Any]],
    working_dir: str | None,
    resume_session_id: str | None,
    cli_path: str,
    model_map: dict[str, str],
    provider_name: str,
    max_turns: int | None = None,
    **kwargs: Any,
) -> Any:
    """Generate with native tool calling using SDK-native permission mechanisms."""
    sdk_session = await _build_tool_message_session(
        messages=messages,
        model=model,
        tools=tools,
        working_dir=working_dir,
        resume_session_id=resume_session_id,
        cli_path=cli_path,
        model_map=model_map,
        provider_name=provider_name,
        max_turns=max_turns,
        **kwargs,
    )
    async for item in _stream_sdk_session_messages(sdk_session, provider_name):
        yield item
