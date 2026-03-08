"""Tool handling and helpers for Claude adapter — permission checking, MCP, and SDK tool execution."""

import logging
from collections.abc import AsyncIterator
from typing import Any

from app.adapters.base import Message, ProviderError
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
from app.adapters.claude_utils import (
    _sdk_semaphore,
    build_sdk_options,
    extract_system_and_conversation,
)

logger = logging.getLogger(__name__)

# Re-export constants callers may reference
_CLI_BUILTIN_TOOLS = frozenset({"bash", "read_file", "write_file"})
_SDK_TOOL_NAME_MAP: dict[str, str] = {
    "Bash": "bash",
    "Read": "read_file",
    "Write": "write_file",
    "Edit": "write_file",
}


def _normalize_tool_name(name: str) -> str:
    """Normalize SDK tool names for permission hooks."""
    return _normalize_tool_name_impl(name)


def _build_can_use_tool(
    checker: Any | None = None,
    project_id: str | None = None,
) -> Any:
    """Build a can_use_tool callback with non-boundary permission layers.

    Composes hooks in order:
      1. Project permission tier (off/read/write/yolo)
      2. Cross-project path enforcement
      3. Per-request PermissionConfig (granular allow/deny via checker)

    Worktree boundary enforcement is handled separately via settings-based
    enforcement in ``_claude_settings.py`` (evaluated inside the subprocess).

    MCP tool names are normalized before passing to hooks since the SDK
    prepends 'mcp__<server>__' but hooks expect bare tool names.
    """
    return _make_can_use_tool_callback(
        _compose_permission_hooks(checker, project_id)
    )


def _build_mcp_server(
    tools: list[dict[str, Any]],
    working_dir: str | None,
    project_id: str | None,
    tool_catalog: list[dict[str, Any]] | None,
) -> Any | None:
    """Build an in-process SDK MCP server for custom tools."""
    return _build_mcp_server_impl(tools, working_dir, project_id, tool_catalog=tool_catalog)


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
                if type(message).__name__ == "ResultMessage":
                    return
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
    max_turns: int | None = None,
    **kwargs: Any,
) -> AsyncIterator[tuple[Any, str | None]]:
    """Generate with native tool calling using SDK-native permission mechanisms."""
    project_id = kwargs.get("project_id")
    tool_catalog = kwargs.get("tool_catalog")
    # Boundary enforcement for Claude SDK is handled via settings-based
    # enforcement (settings + PreToolUse hook) — see _claude_settings.py.
    # The can_use_tool callback here is only for non-boundary permission
    # hooks (project tier, per-request checker) since the SDK subprocess
    # does not invoke can_use_tool for built-in tools.
    has_permission_hooks = bool(permission_checker or project_id)
    can_use_tool_cb = (
        _build_can_use_tool(
            checker=permission_checker if not yolo_mode else None,
            project_id=project_id if not yolo_mode else None,
        )
        if has_permission_hooks and not yolo_mode
        else None
    )
    mcp_server = _build_mcp_server(tools, working_dir, project_id, tool_catalog) if tools else None
    mcp_servers = {"agent-hub": mcp_server} if mcp_server else None

    # Build allowed_tools list including MCP tool names so Claude CLI
    # doesn't reject them (allowed_tools doesn't support wildcards).
    from app.adapters._claude_constants import build_allowed_tools

    allowed_tools = build_allowed_tools(tools) if tools else None

    system_prompt, conversation_prompt = extract_system_and_conversation(messages)

    options, use_streaming_prompt = build_sdk_options(
        cli_path=cli_path,
        model=model,
        model_map=model_map,
        working_dir=working_dir,
        yolo_mode=yolo_mode,
        can_use_tool=can_use_tool_cb,
        mcp_servers=mcp_servers,
        resume_session_id=resume_session_id,
        max_turns=max_turns,
        system_prompt=system_prompt,
        allowed_tools=allowed_tools,
    )
    prompt: str | Any = await _wrap_prompt_as_stream(conversation_prompt) if use_streaming_prompt else conversation_prompt
    async for item in _stream_sdk_messages(prompt, options, provider_name):
        yield item
