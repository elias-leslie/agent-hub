"""Tool handling and helpers for Claude adapter — permission checking, MCP, and SDK tool execution."""

import asyncio
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from app.adapters._claude_result_metadata import (
    normalized_stop_reason,
    resolve_result_finish_reason,
)
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
from app.adapters.claude_tools_sdk_query import (
    _close_internal_query,  # re-exported: tests import from this module
    _close_sdk_message_iter,
    _sdk_query_messages,
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

# Silence unused-import lint — _close_internal_query is re-exported for callers
__all__ = ["_close_internal_query"]


@dataclass
class ResultMessage:
    """Fallback terminal message when the Claude SDK omits its final result frame."""

    subtype: str = "success"
    duration_ms: int = 0
    duration_api_ms: int = 0
    is_error: bool = False
    num_turns: int = 0
    session_id: str | None = None
    stop_reason: str | None = None
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    result: str | None = None
    structured_output: Any = None
    finish_reason: str | None = None


@dataclass
class ErrorMessage:
    """Terminal message carrying a tool-stream error without raising through the iterator."""

    error: str


async def _wrap_prompt_as_stream(prompt: str) -> Any:
    """Wrap a string prompt as an async iterable for SDK streaming callers."""

    async def _stream() -> Any:
        yield {
            "type": "user",
            "message": {"role": "user", "content": prompt},
            "parent_tool_use_id": None,
            "session_id": None,
        }

    return _stream()


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


def _message_has_block_type(message: Any, block_type: str) -> bool:
    """Return True if any content block in message matches block_type."""
    return any(
        extract_block_content(b)["type"] == block_type
        for b in getattr(message, "content", []) or []
    )


async def _fetch_next_or_stop(
    message_iter: Any,
    idle_timeout: float | None,
    provider_name: str,
) -> Any:
    """Fetch next message; return _STREAM_STOP on exhaustion, raise ProviderError on timeout."""
    try:
        if idle_timeout is None:
            return await anext(message_iter)
        async with asyncio.timeout(idle_timeout):
            return await anext(message_iter)
    except StopAsyncIteration:
        return _STREAM_STOP
    except TimeoutError as exc:
        logger.warning("Claude SDK timed out after post-tool stall; skipping explicit iterator close")
        msg = f"Claude SDK stalled after tool_result for {idle_timeout:.1f}s"
        logger.error(msg)
        raise ProviderError(msg, provider=provider_name, retriable=True) from exc


def _log_idle_watchdog_transition(
    idle_timeout: float | None,
    idle_watch_armed: bool,
    session_id: str | None,
    pending_tool_calls: int,
    done_emitted: bool,
) -> bool:
    """Log watchdog arm/disarm transitions and return new armed state."""
    if idle_timeout is not None and not idle_watch_armed:
        logger.warning(
            "Claude SDK post-tool idle watchdog armed: session_id=%s timeout=%.1fs",
            session_id,
            idle_timeout,
        )
        return True
    if idle_timeout is None and idle_watch_armed:
        logger.info(
            "Claude SDK post-tool idle watchdog cleared: session_id=%s pending_tool_calls=%d done=%s",
            session_id,
            pending_tool_calls,
            done_emitted,
        )
        return False
    return idle_watch_armed


def _resolve_result_message(
    message: Any,
    session_id: str | None,
    configured_max_turns: int | None,
) -> Any:
    """Annotate or reconstruct a ResultMessage with resolved finish/stop reasons."""
    resolved_finish_reason = resolve_result_finish_reason(
        message,
        configured_max_turns=configured_max_turns,
    )
    resolved_stop_reason = normalized_stop_reason(
        message,
        configured_max_turns=configured_max_turns,
    )
    try:
        message.finish_reason = resolved_finish_reason
        if resolved_stop_reason is not None:
            message.stop_reason = resolved_stop_reason
    except Exception:
        logger.debug("Failed to set finish_reason on SDK message, reconstructing", exc_info=True)
        message = ResultMessage(
            session_id=session_id,
            subtype=getattr(message, "subtype", "success"),
            stop_reason=resolved_stop_reason,
            finish_reason=resolved_finish_reason,
            result=getattr(message, "result", None),
            usage=getattr(message, "usage", None),
            structured_output=getattr(message, "structured_output", None),
            total_cost_usd=getattr(message, "total_cost_usd", None),
            num_turns=getattr(message, "num_turns", 0),
            is_error=getattr(message, "is_error", False),
            duration_ms=getattr(message, "duration_ms", 0),
            duration_api_ms=getattr(message, "duration_api_ms", 0),
        )
    return message


def _update_tool_call_count(message: Any, pending_tool_calls: int) -> int:
    """Track pending tool calls based on tool_use / tool_result blocks."""
    if _message_has_block_type(message, "tool_use"):
        pending_tool_calls += 1
    if _message_has_block_type(message, "tool_result"):
        pending_tool_calls = max(0, pending_tool_calls - 1)
    return pending_tool_calls


async def _iterate_sdk_messages(
    prompt: str | Any,
    options: Any,
    provider_name: str,
) -> AsyncGenerator[tuple[Any, str | None]]:
    """Core message-processing loop over the claude_agent_sdk query iterator."""
    session_id: str | None = None
    done_emitted = False
    saw_payload = False
    pending_tool_calls = 0
    configured_max_turns = getattr(options, "max_turns", None)
    idle_watch_armed = False
    skip_iterator_close = False
    iterator_closed = False
    message_iter = _sdk_query_messages(prompt, options).__aiter__()
    try:
        while True:
            idle_timeout = (
                _SDK_POST_TOOL_IDLE_TIMEOUT_SECONDS
                if saw_payload and pending_tool_calls == 0 and not done_emitted
                else None
            )
            idle_watch_armed = _log_idle_watchdog_transition(
                idle_timeout, idle_watch_armed, session_id, pending_tool_calls, done_emitted,
            )
            try:
                message = await _fetch_next_or_stop(message_iter, idle_timeout, provider_name)
            except ProviderError as exc:
                if "stalled after tool_result" in str(exc):
                    skip_iterator_close = True
                raise exc
            if message is _STREAM_STOP:
                if saw_payload and not done_emitted:
                    finish_reason = "end_turn"
                    logger.warning(
                        "Claude SDK stream ended without ResultMessage; synthesizing terminal result (%s)",
                        finish_reason,
                    )
                    yield (
                        ResultMessage(session_id=session_id, stop_reason=finish_reason, finish_reason=finish_reason),
                        session_id,
                    )
                await _close_sdk_message_iter(message_iter)
                iterator_closed = True
                return
            if hasattr(message, "subtype") and message.subtype == "init" and hasattr(message, "data"):
                session_id = message.data.get("session_id")
                if session_id:
                    logger.info(f"Claude SDK session ID: {session_id}")
                continue
            if type(message).__name__ == "ResultMessage":
                message = _resolve_result_message(message, session_id, configured_max_turns)
                yield (message, session_id)
                done_emitted = True
                await _close_sdk_message_iter(message_iter)
                iterator_closed = True
                return
            if done_emitted:
                continue
            saw_payload = True
            pending_tool_calls = _update_tool_call_count(message, pending_tool_calls)
            yield (message, session_id)
    finally:
        if idle_watch_armed:
            logger.info("Claude SDK idle watchdog still armed during iterator unwind: session_id=%s", session_id)
        if skip_iterator_close:
            logger.info("Claude SDK iterator close skipped after idle-timeout unwind: session_id=%s", session_id)
        elif not iterator_closed:
            with suppress(asyncio.CancelledError):
                await _close_sdk_message_iter(message_iter)


async def _stream_sdk_messages(
    prompt: str | Any,
    options: Any,
    provider_name: str,
) -> AsyncIterator[tuple[Any, str | None]]:
    """Yield (message, session_id) pairs from claude_agent_sdk query.

    Iterates the SDK directly in the calling task to preserve anyio's
    task-local cancel-scope tracking.  The previous producer-task + queue
    pattern broke this invariant, causing ``CancelScope._deliver_cancellation``
    to spin at 100 % CPU when the stream was cancelled.
    """
    async with _sdk_semaphore:
        inner_iter = _iterate_sdk_messages(prompt, options, provider_name)
        try:
            async for item in inner_iter:
                yield item
        except Exception as e:
            error_msg = f"Claude tool error: {e}"
            logger.error(error_msg)
            yield (ErrorMessage(error=error_msg), None)
        finally:
            await inner_iter.aclose()


def _build_tool_infra(
    tools: list[dict[str, Any]],
    working_dir: str | None,
    project_id: str | None,
    agent_slug: str | None,
    tool_catalog: list[dict[str, Any]] | None,
    yolo_mode: bool,
    permission_checker: Any | None,
) -> tuple[Any | None, dict[str, Any] | None, list[str] | None]:
    """Build can_use_tool callback, MCP servers dict, and allowed_tools list."""
    # Boundary enforcement for Claude SDK is handled via settings-based
    # enforcement (settings + PreToolUse hook) — see _claude_settings.py.
    # The can_use_tool callback here is only for non-boundary permission
    # hooks (project tier, per-request checker) since the SDK subprocess
    # does not invoke can_use_tool for built-in tools.
    can_use_tool_cb = _resolve_can_use_tool(yolo_mode, permission_checker, project_id, agent_slug)
    mcp_server = _build_mcp_server(tools, working_dir, project_id, agent_slug, tool_catalog) if tools else None
    mcp_servers = {"agent-hub": mcp_server} if mcp_server else None

    from app.adapters._claude_constants import build_allowed_tools

    allowed_tools = build_allowed_tools(tools) if tools else None
    return can_use_tool_cb, mcp_servers, allowed_tools


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

    can_use_tool_cb, mcp_servers, allowed_tools = _build_tool_infra(
        tools, working_dir, project_id, agent_slug, tool_catalog, yolo_mode, permission_checker,
    )
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
    # Working-dir sessions use settings/hooks for permission enforcement and
    # stay on plain-string prompts to avoid async-input cancel-scope corruption.
    prompt: str | Any = (
        conversation_prompt
        if working_dir
        else await _wrap_prompt_as_stream(conversation_prompt) if use_streaming_prompt else conversation_prompt
    )
    async for item in _stream_sdk_messages(prompt, options, provider_name):
        yield item
