"""Tool execution loop for streaming completions."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from app.adapters.base import Message

from .schemas import StreamingChunk
from .streaming_context import StreamContext
from .streaming_persistence import build_done_sse, log_tool_audit

if TYPE_CHECKING:
    from app.adapters.types import StreamEvent
    from app.services.tools.base import ToolCall, ToolHandler, ToolResult

logger = logging.getLogger(__name__)

DEFAULT_MAX_TOOL_TURNS = 15

_TOOL_MAX_RETRIES = 3
_TOOL_RETRY_BASE_DELAY = 2.0
_TOOL_RETRY_MAX_DELAY = 30.0

_TRANSIENT_ERROR_PATTERNS = (
    "429", "rate limit", "Rate limit",
    "503", "service unavailable", "Service Unavailable",
    "timeout", "timed out", "Timeout", "Timed out",
    "connection refused", "Connection refused",
    "connection reset", "Connection reset",
    "UNAVAILABLE", "RESOURCE_EXHAUSTED",
)


def is_transient_tool_error(error_content: str) -> bool:
    """Return True if error_content matches a known transient failure pattern."""
    return any(pattern in error_content for pattern in _TRANSIENT_ERROR_PATTERNS)


async def execute_tool_with_retry(
    handler: ToolHandler,
    tool_call: ToolCall,
    max_retries: int = _TOOL_MAX_RETRIES,
) -> ToolResult:
    """Execute a tool call with exponential-backoff retry for transient failures."""
    result = await handler.execute(tool_call)
    for attempt in range(1, max_retries):
        if not result.is_error or not is_transient_tool_error(result.content):
            return result
        delay = min(_TOOL_RETRY_BASE_DELAY * (2 ** (attempt - 1)), _TOOL_RETRY_MAX_DELAY)
        logger.warning(
            "Transient tool error (attempt %d/%d), retrying in %.1fs: %s",
            attempt, max_retries, delay, result.content[:200],
        )
        await asyncio.sleep(delay)
        result = await handler.execute(tool_call)
    return result


def build_assistant_content_blocks(
    text_content: str,
    tool_calls: list[StreamEvent],
) -> list[dict[str, object]]:
    """Build Anthropic-format content blocks for an assistant message.

    Preserves ``thought_signature`` so CloudCode PA can validate
    thinking-enabled function calls on subsequent turns.
    """
    blocks: list[dict[str, object]] = []
    if text_content:
        blocks.append({"type": "text", "text": text_content})
    for tc in tool_calls:
        block: dict[str, object] = {
            "type": "tool_use",
            "id": tc.tool_id,
            "name": tc.tool_name,
            "input": tc.tool_input or {},
        }
        if tc.thought_signature:
            block["thought_signature"] = tc.thought_signature
        blocks.append(block)
    return blocks


def build_tool_result_blocks(
    results: list[tuple[str, str, str, bool]],
) -> list[dict[str, object]]:
    """Build tool_result content blocks for a user message.

    Args:
        results: List of (tool_use_id, tool_name, content, is_error) tuples.
    """
    blocks: list[dict[str, object]] = []
    for tool_use_id, tool_name, content, is_error in results:
        block: dict[str, object] = {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "tool_name": tool_name,
            "content": content,
        }
        if is_error:
            block["is_error"] = True
        blocks.append(block)
    return blocks


def sse_for_simple_event(
    event: object,
    content_buf: list[str],
    ctx: StreamContext,
) -> str | None:
    """Return SSE string for content/tool_use/tool_result/error events; None otherwise."""
    event_type = getattr(event, "type", None)
    if event_type == "content":
        content_buf[0] += getattr(event, "content", None) or ""
        chunk = StreamingChunk(
            type="content", seq=ctx.next_seq(), content=getattr(event, "content", None)
        )
        return f"data: {chunk.model_dump_json()}\n\n"
    if event_type == "tool_use":
        chunk = StreamingChunk(
            type="tool_use",
            seq=ctx.next_seq(),
            tool_id=getattr(event, "tool_id", None),
            tool_name=getattr(event, "tool_name", None),
            tool_input=getattr(event, "tool_input", None),
        )
        return f"data: {chunk.model_dump_json()}\n\n"
    if event_type == "tool_result":
        chunk = StreamingChunk(
            type="tool_result",
            seq=ctx.next_seq(),
            tool_id=getattr(event, "tool_id", None),
            tool_result=getattr(event, "content", None),
            tool_status="complete",
        )
        return f"data: {chunk.model_dump_json()}\n\n"
    if event_type == "thinking":
        chunk = StreamingChunk(
            type="thinking", seq=ctx.next_seq(), content=getattr(event, "content", None)
        )
        return f"data: {chunk.model_dump_json()}\n\n"
    if event_type == "error":
        error_chunk = StreamingChunk(
            type="error", seq=ctx.next_seq(), error=getattr(event, "error", None)
        )
        return f"data: {error_chunk.model_dump_json()}\n\n"
    return None


async def _execute_single_tool(
    tc_event: StreamEvent,
    handler: ToolHandler,
    ctx: StreamContext,
) -> tuple[tuple[str, str, str, bool] | None, list[str]]:
    """Execute one tool call; returns (result_tuple, sse_parts) or (None, [cancel_sse]).

    When the user cancels, result_tuple is None and sse_parts contains the cancel SSE.
    """
    if ctx.cancel_event and ctx.cancel_event.is_set():
        logger.info("Streaming: user cancelled tool execution for session %s", ctx.session_id)
        cancelled_chunk = StreamingChunk(
            type="cancelled", seq=ctx.next_seq(),
            session_id=ctx.session_id, provider=ctx.provider, model=ctx.model,
        )
        return None, [f"data: {cancelled_chunk.model_dump_json()}\n\n"]

    from app.services.tools.base import ToolCall

    tool_name = tc_event.tool_name or ""
    tool_call = ToolCall(
        id=tc_event.tool_id or "",
        name=tool_name,
        input=tc_event.tool_input or {},
    )

    start_sse = f"data: {StreamingChunk(type='tool_start', seq=ctx.next_seq(), tool_id=tool_call.id, tool_name=tool_name).model_dump_json()}\n\n"
    result = await execute_tool_with_retry(handler, tool_call)

    from app.services.tools.tool_handler import SENSITIVE_TOOLS

    sensitivity = SENSITIVE_TOOLS.get(tool_name)
    if sensitivity:
        log_tool_audit(
            session_id=ctx.session_id,
            tool_name=tool_name,
            tool_input=tc_event.tool_input or {},
            result_content=result.content,
            is_error=result.is_error,
            duration_ms=result.duration_ms,
            sensitivity=sensitivity,
            agent_id=ctx.agent_used,
        )

    status = "error" if result.is_error else "complete"
    result_sse = f"data: {StreamingChunk(type='tool_result', seq=ctx.next_seq(), tool_id=result.tool_use_id, tool_result=result.content, tool_status=status).model_dump_json()}\n\n"
    return (result.tool_use_id, tool_call.name, result.content, result.is_error), [start_sse, result_sse]


async def _collect_turn_events(
    adapter: object,
    current_messages: list[Message],
    model: str,
    max_tokens: int | None,
    temperature: float,
    stream_kwargs: dict[str, object],
    content_buf: list[str],
    ctx: StreamContext,
) -> tuple[list[str], list[StreamEvent], set[str], str, object | None]:
    """Stream one turn and collect: sse_parts, tool_calls, resolved_ids, turn_text, done_event."""
    sse_parts: list[str] = []
    pending_tool_calls: list[StreamEvent] = []
    resolved_tool_ids: set[str] = set()
    turn_text = ""
    done_event: object | None = None

    async for event in adapter.stream(  # type: ignore[attr-defined]
        messages=current_messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        **stream_kwargs,
    ):
        if getattr(event, "type", None) == "done":
            done_event = event
            break
        if getattr(event, "type", None) == "tool_use":
            pending_tool_calls.append(event)
        if getattr(event, "type", None) == "tool_result" and getattr(event, "tool_id", None):
            resolved_tool_ids.add(event.tool_id)
        if getattr(event, "type", None) == "content":
            turn_text += getattr(event, "content", None) or ""
        sse = sse_for_simple_event(event, content_buf, ctx)
        if sse is not None:
            sse_parts.append(sse)

    return sse_parts, pending_tool_calls, resolved_tool_ids, turn_text, done_event


async def _run_unresolved_tools(
    unresolved: list[StreamEvent],
    handler: ToolHandler,
    ctx: StreamContext,
    turn: int,
) -> tuple[list[tuple[str, str, str, bool]], list[str], bool]:
    """Execute each unresolved tool call; return (result_tuples, sse_parts, cancelled)."""
    logger.info(
        "Streaming turn %d: executing %d tool(s) for session %s",
        turn, len(unresolved), ctx.session_id,
    )
    tool_result_tuples: list[tuple[str, str, str, bool]] = []
    sse_parts: list[str] = []
    for tc_event in unresolved:
        result_tuple, tool_sses = await _execute_single_tool(tc_event, handler, ctx)
        if result_tuple is None:
            return [], tool_sses, True
        tool_result_tuples.append(result_tuple)
        sse_parts.extend(tool_sses)
    return tool_result_tuples, sse_parts, False


def _append_turn_messages(
    current_messages: list[Message],
    turn_text: str,
    pending_tool_calls: list[StreamEvent],
    result_tuples: list[tuple[str, str, str, bool]],
) -> None:
    """Append assistant + user tool-result messages for the next turn."""
    current_messages.append(
        Message(role="assistant", content=build_assistant_content_blocks(turn_text, pending_tool_calls))
    )
    current_messages.append(
        Message(role="user", content=build_tool_result_blocks(result_tuples))
    )


async def iter_stream_sse_with_tools(
    adapter: object,
    messages: list[Message],
    model: str,
    max_tokens: int | None,
    temperature: float,
    stream_kwargs: dict[str, object],
    content_buf: list[str],
    ctx: StreamContext,
    project_id: str | None,
    max_tool_turns: int = DEFAULT_MAX_TOOL_TURNS,
) -> AsyncIterator[str]:
    """Yield SSE strings with provider-agnostic tool execution loop."""
    from app.services.tools.tool_handler import create_direct_handler

    handler = create_direct_handler(
        working_dir=stream_kwargs.get("working_dir"), project_id=project_id,
    )
    current_messages = list(messages)

    for turn in range(1, max_tool_turns + 1):
        turn_sses, pending_calls, resolved_ids, turn_text, done_event = (
            await _collect_turn_events(
                adapter, current_messages, model, max_tokens,
                temperature, stream_kwargs, content_buf, ctx,
            )
        )
        for part in turn_sses:
            yield part
        if done_event is None:
            return
        unresolved = [tc for tc in pending_calls if tc.tool_id not in resolved_ids]
        if not unresolved:
            yield await build_done_sse(
                event=done_event, ctx=ctx,
                accumulated_content=content_buf[0], seq=ctx.next_seq(),
            )
            return
        result_tuples, tool_sses, cancelled = await _run_unresolved_tools(
            unresolved, handler, ctx, turn,
        )
        for sse in tool_sses:
            yield sse
        if cancelled:
            return
        _append_turn_messages(current_messages, turn_text, pending_calls, result_tuples)

    logger.warning("Streaming: reached max tool turns (%d) for session %s", max_tool_turns, ctx.session_id)
    yield f"data: {StreamingChunk(type='error', seq=ctx.next_seq(), error=f'Tool execution reached maximum turns ({max_tool_turns})').model_dump_json()}\n\n"
