"""Tool handling and helpers for Claude adapter — permission checking, MCP, and SDK tool execution."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
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
    extract_block_content,
    extract_system_and_conversation,
)

logger = logging.getLogger(__name__)
_SDK_POST_TOOL_IDLE_TIMEOUT_SECONDS = 300.0

# Re-export constants callers may reference
_CLI_BUILTIN_TOOLS = frozenset({"bash", "read_file", "write_file"})
_SDK_TOOL_NAME_MAP: dict[str, str] = {
    "Bash": "bash",
    "Read": "read_file",
    "Write": "write_file",
    "Edit": "write_file",
}

_STREAM_STOP = object()  # Sentinel: async iteration exhausted


@dataclass
class ResultMessage:
    """Fallback terminal message when the Claude SDK omits its final result frame."""

    subtype: str = "result"
    duration_ms: int = 0
    duration_api_ms: int = 0
    is_error: bool = False
    num_turns: int = 0
    session_id: str | None = None
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    result: str | None = None
    structured_output: Any = None


def _normalize_tool_name(name: str) -> str:
    """Normalize SDK tool names for permission hooks."""
    return _normalize_tool_name_impl(name)


def _build_can_use_tool(
    checker: Any | None = None,
    project_id: str | None = None,
    agent_slug: str | None = None,
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
        _compose_permission_hooks(checker, project_id),
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
    yolo_mode: bool,
    permission_checker: Any | None,
    project_id: str | None,
    agent_slug: str | None,
) -> Any | None:
    """Return can_use_tool callback when permission hooks are needed, else None."""
    if yolo_mode and agent_slug != "persona":
        return None
    if not (permission_checker or project_id or agent_slug == "persona"):
        return None
    return _build_can_use_tool(
        checker=permission_checker,
        project_id=project_id,
        agent_slug=agent_slug,
    )


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


async def _abort_message_iter(message_iter: Any, next_task: asyncio.Task[Any] | None) -> None:
    if hasattr(message_iter, "aclose"):
        with suppress(Exception):
            await message_iter.aclose()
    if next_task is not None:
        next_task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await asyncio.wait_for(next_task, timeout=1.0)


async def _next_message(message_iter: Any, idle_timeout: float | None) -> Any:
    if idle_timeout is None:
        return await anext(message_iter)
    next_task = asyncio.create_task(anext(message_iter))
    done, _pending = await asyncio.wait({next_task}, timeout=idle_timeout)
    if next_task in done:
        return await next_task
    await _abort_message_iter(message_iter, next_task)
    raise TimeoutError(f"Claude SDK stalled after tool_result for {idle_timeout:.1f}s")


def _message_has_tool_use(message: Any) -> bool:
    for block in getattr(message, "content", []) or []:
        if extract_block_content(block)["type"] == "tool_use":
            return True
    return False


def _message_has_tool_result(message: Any) -> bool:
    for block in getattr(message, "content", []) or []:
        if extract_block_content(block)["type"] == "tool_result":
            return True
    return False


async def _fetch_next_or_stop(
    message_iter: Any,
    idle_timeout: float | None,
    provider_name: str,
) -> Any:
    """Fetch next message, return _STREAM_STOP on exhaustion, raise ProviderError on timeout."""
    try:
        return await _next_message(message_iter, idle_timeout)
    except StopAsyncIteration:
        return _STREAM_STOP
    except TimeoutError as exc:
        logger.error(str(exc))
        raise ProviderError(str(exc), provider=provider_name, retriable=True) from exc


async def _iterate_sdk_messages(
    prompt: str | Any,
    options: Any,
    provider_name: str,
) -> AsyncIterator[tuple[Any, str | None]]:
    """Core message-processing loop over the claude_agent_sdk query iterator."""
    from claude_agent_sdk import query

    session_id: str | None = None
    done_emitted = False
    saw_payload = False
    pending_tool_calls = 0
    message_iter = query(prompt=prompt, options=options).__aiter__()
    while True:
        idle_timeout = (
            _SDK_POST_TOOL_IDLE_TIMEOUT_SECONDS
            if saw_payload and pending_tool_calls == 0 and not done_emitted
            else None
        )
        message = await _fetch_next_or_stop(message_iter, idle_timeout, provider_name)
        if message is _STREAM_STOP:
            if saw_payload and not done_emitted:
                logger.warning(
                    "Claude SDK stream ended without ResultMessage; synthesizing terminal result"
                )
                yield (ResultMessage(session_id=session_id), session_id)
            return
        if hasattr(message, "subtype") and message.subtype == "init" and hasattr(message, "data"):
            session_id = message.data.get("session_id")
            if session_id:
                logger.info(f"Claude SDK session ID: {session_id}")
            continue
        if type(message).__name__ == "ResultMessage":
            yield (message, session_id)
            done_emitted = True
            continue
        if done_emitted:
            continue
        saw_payload = True
        if _message_has_tool_use(message):
            pending_tool_calls += 1
        if _message_has_tool_result(message):
            pending_tool_calls = max(0, pending_tool_calls - 1)
        yield (message, session_id)


async def _stream_sdk_messages(
    prompt: str | Any,
    options: Any,
    provider_name: str,
) -> AsyncIterator[tuple[Any, str | None]]:
    """Yield (message, session_id) pairs from claude_agent_sdk query."""
    async with _sdk_semaphore:
        try:
            async for item in _iterate_sdk_messages(prompt, options, provider_name):
                yield item
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
    agent_slug = kwargs.get("agent_slug")
    tool_catalog = kwargs.get("tool_catalog")
    # Boundary enforcement for Claude SDK is handled via settings-based
    # enforcement (settings + PreToolUse hook) — see _claude_settings.py.
    # The can_use_tool callback here is only for non-boundary permission
    # hooks (project tier, per-request checker) since the SDK subprocess
    # does not invoke can_use_tool for built-in tools.
    can_use_tool_cb = _resolve_can_use_tool(yolo_mode, permission_checker, project_id, agent_slug)
    mcp_server = _build_mcp_server(
        tools,
        working_dir,
        project_id,
        agent_slug,
        tool_catalog,
    ) if tools else None
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
        agent_slug=agent_slug,
    )
    prompt: str | Any = await _wrap_prompt_as_stream(conversation_prompt) if use_streaming_prompt else conversation_prompt
    async for item in _stream_sdk_messages(prompt, options, provider_name):
        yield item
