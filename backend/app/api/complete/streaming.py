"""Streaming completion logic for completion API."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import Message
from app.models import Session as DBSession

from .event_helpers import save_events
from .helpers import get_adapter
from .schemas import MessageInput, StreamingChunk

if TYPE_CHECKING:
    from app.adapters.types import StreamEvent

logger = logging.getLogger(__name__)

# Maximum turns for streaming tool execution to prevent infinite loops
_MAX_TOOL_TURNS = 15


async def _save_messages_to_db(
    session_id: str,
    user_messages: list[MessageInput],
    accumulated_content: str,
    input_tokens: int,
    output_tokens: int,
    model: str,
    agent_used: str | None,
    stream_start: float,
) -> None:
    """Save streamed messages to the database using a fresh session."""
    if not user_messages or not accumulated_content:
        return
    try:
        from app.db import async_session

        stream_duration_ms = int((time.monotonic() - stream_start) * 1000)
        async with async_session() as fresh_db:
            await save_events(
                db=fresh_db,
                session_id=session_id,
                user_messages=user_messages,
                assistant_content=accumulated_content,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model_used=model,
                agent_id=agent_used,
                duration_ms=stream_duration_ms,
            )
            logger.info(f"Streaming: saved messages for session {session_id}")
    except Exception as save_err:
        logger.error(f"Failed to save streaming messages: {save_err}")


async def _close_one_shot_session(session_id: str) -> None:
    """Mark a one-shot session as completed in the database."""
    try:
        from sqlalchemy import select

        from app.db import async_session

        async with async_session() as fresh_db:
            result = await fresh_db.execute(
                select(DBSession).where(DBSession.id == session_id)
            )
            session = result.scalar_one_or_none()
            if session:
                session.status = "completed"
                await fresh_db.commit()
                logger.info(f"Streaming: closed one-shot session {session_id}")
    except Exception as close_err:
        logger.error(f"Failed to close one-shot session: {close_err}")


async def _build_done_sse(
    event: object,
    session_id: str,
    model: str,
    provider: str,
    agent_used: str | None,
    model_used: str | None,
    fallback_used: bool,
    user_messages: list[MessageInput] | None,
    accumulated_content: str,
    stream_start: float,
    is_new_session: bool,
    is_one_shot: bool,
) -> str:
    """Persist completion data and return the SSE done chunk string."""
    input_tokens = event.input_tokens if event.input_tokens is not None else 0  # type: ignore[attr-defined]
    output_tokens = event.output_tokens if event.output_tokens is not None else 0  # type: ignore[attr-defined]
    await _save_messages_to_db(
        session_id=session_id,
        user_messages=user_messages or [],
        accumulated_content=accumulated_content,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
        agent_used=agent_used,
        stream_start=stream_start,
    )
    if is_new_session and is_one_shot:
        await _close_one_shot_session(session_id)
    # Calculate cost from token counts
    from app.services.token_counter import estimate_cost

    cost = estimate_cost(input_tokens, output_tokens, model)

    thinking_tokens = getattr(event, "thinking_tokens", None)

    done_chunk = StreamingChunk(
        type="done",
        model=model,
        provider=provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        finish_reason=event.finish_reason,  # type: ignore[attr-defined]
        session_id=session_id,
        agent_used=agent_used,
        model_used=model_used,
        fallback_used=fallback_used if agent_used else None,
        cost_usd=cost.total_cost_usd,
        thinking_tokens=thinking_tokens,
    )
    return f"data: {done_chunk.model_dump_json()}\n\n"


def _sse_for_simple_event(event: object, content_buf: list[str]) -> str | None:
    """Return SSE string for content/tool_use/error events; None for unknown types."""
    event_type = event.type  # type: ignore[attr-defined]
    if event_type == "content":
        content_buf[0] += event.content or ""  # type: ignore[attr-defined]
        chunk = StreamingChunk(type="content", content=event.content)  # type: ignore[attr-defined]
        return f"data: {chunk.model_dump_json()}\n\n"
    if event_type == "tool_use":
        chunk = StreamingChunk(
            type="tool_use",
            tool_id=event.tool_id,  # type: ignore[attr-defined]
            tool_name=event.tool_name,  # type: ignore[attr-defined]
            tool_input=event.tool_input,  # type: ignore[attr-defined]
        )
        return f"data: {chunk.model_dump_json()}\n\n"
    if event_type == "error":
        error_chunk = StreamingChunk(type="error", error=event.error)  # type: ignore[attr-defined]
        return f"data: {error_chunk.model_dump_json()}\n\n"
    return None


class _StreamContext:
    """Holds context needed while iterating stream events."""

    __slots__ = (
        "agent_used", "fallback_used", "is_new_session", "is_one_shot",
        "model", "model_used", "provider", "session_id", "stream_start",
        "user_messages",
    )

    def __init__(
        self,
        session_id: str,
        model: str,
        provider: str,
        agent_used: str | None,
        model_used: str | None,
        fallback_used: bool,
        user_messages: list[MessageInput] | None,
        stream_start: float,
        is_new_session: bool,
        is_one_shot: bool,
    ) -> None:
        self.session_id = session_id
        self.model = model
        self.provider = provider
        self.agent_used = agent_used
        self.model_used = model_used
        self.fallback_used = fallback_used
        self.user_messages = user_messages
        self.stream_start = stream_start
        self.is_new_session = is_new_session
        self.is_one_shot = is_one_shot


async def _iter_stream_sse(adapter: object, messages: object, model: str, max_tokens: object, temperature: float, stream_kwargs: dict[str, object], content_buf: list[str], ctx: _StreamContext) -> AsyncIterator[str]:
    """Yield SSE strings from adapter stream events (no tool execution)."""
    async for event in adapter.stream(messages=messages, model=model, max_tokens=max_tokens, temperature=temperature, **stream_kwargs):  # type: ignore[attr-defined]
        if event.type == "done":
            yield await _build_done_sse(event=event, session_id=ctx.session_id, model=ctx.model, provider=ctx.provider, agent_used=ctx.agent_used, model_used=ctx.model_used, fallback_used=ctx.fallback_used, user_messages=ctx.user_messages, accumulated_content=content_buf[0], stream_start=ctx.stream_start, is_new_session=ctx.is_new_session, is_one_shot=ctx.is_one_shot)
            continue
        sse = _sse_for_simple_event(event, content_buf)
        if sse is not None:
            yield sse


def _build_assistant_content_blocks(
    text_content: str,
    tool_calls: list[StreamEvent],
) -> list[dict[str, Any]]:
    """Build Anthropic-format content blocks for an assistant message.

    Combines streamed text with tool_use blocks into the format expected
    by the API for multi-turn tool conversations.

    Preserves ``thought_signature`` from StreamEvents so that CloudCode PA
    can validate thinking-enabled function calls on subsequent turns.
    """
    blocks: list[dict[str, Any]] = []
    if text_content:
        blocks.append({"type": "text", "text": text_content})
    for tc in tool_calls:
        block: dict[str, Any] = {
            "type": "tool_use",
            "id": tc.tool_id,
            "name": tc.tool_name,
            "input": tc.tool_input or {},
        }
        if tc.thought_signature:
            block["thought_signature"] = tc.thought_signature
        blocks.append(block)
    return blocks


def _build_tool_result_blocks(
    results: list[tuple[str, str, str, bool]],
) -> list[dict[str, Any]]:
    """Build tool_result content blocks for a user message.

    Uses Anthropic-style format with extra ``tool_name`` field so Gemini
    message converters can map to ``functionResponse``.

    Args:
        results: List of (tool_use_id, tool_name, content, is_error) tuples.
    """
    blocks: list[dict[str, Any]] = []
    for tool_use_id, tool_name, content, is_error in results:
        block: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "tool_name": tool_name,
            "content": content,
        }
        if is_error:
            block["is_error"] = True
        blocks.append(block)
    return blocks


async def _iter_stream_sse_with_tools(
    adapter: object,
    messages: list[Message],
    model: str,
    max_tokens: int | None,
    temperature: float,
    stream_kwargs: dict[str, object],
    content_buf: list[str],
    ctx: _StreamContext,
    project_id: str | None,
) -> AsyncIterator[str]:
    """Yield SSE strings with tool execution loop.

    When the model requests tool calls, this function executes them via
    DirectToolHandler, yields tool_result SSE events, rebuilds messages
    with the results, and re-streams.  Detects tool calls by checking for
    pending tool_use events (provider-agnostic — works with Claude's
    finish_reason="tool_use" and Gemini's finish_reason="STOP").
    Continues until the model stops requesting tools or max turns is reached.
    """
    from app.services.tools.base import ToolCall
    from app.services.tools.tool_handler import create_direct_handler

    # Normalize common Gemini tool name variants to expected names
    _TOOL_NAME_ALIASES: dict[str, str] = {
        "execute_bash": "bash",
        "execute_command": "bash",
        "run_bash": "bash",
        "file_read": "read_file",
        "file_write": "write_file",
    }

    handler = create_direct_handler(project_id=project_id)
    current_messages = list(messages)
    turn = 0

    while turn < _MAX_TOOL_TURNS:
        turn += 1
        pending_tool_calls: list[StreamEvent] = []
        turn_text = ""
        done_event: object | None = None

        async for event in adapter.stream(  # type: ignore[attr-defined]
            messages=current_messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            **stream_kwargs,
        ):
            if event.type == "done":
                done_event = event
                break

            if event.type == "tool_use":
                pending_tool_calls.append(event)

            # Accumulate text for message rebuilding
            if event.type == "content":
                turn_text += event.content or ""

            sse = _sse_for_simple_event(event, content_buf)
            if sse is not None:
                yield sse

        if done_event is None:
            # Stream ended without done event (error already yielded by adapter)
            return

        # If no tool calls were collected, we're done.
        # Check pending_tool_calls (not finish_reason) because Gemini uses
        # "STOP" even when tool calls are present, while Claude uses "tool_use".
        if not pending_tool_calls:
            yield await _build_done_sse(
                event=done_event, session_id=ctx.session_id,
                model=ctx.model, provider=ctx.provider,
                agent_used=ctx.agent_used, model_used=ctx.model_used,
                fallback_used=ctx.fallback_used, user_messages=ctx.user_messages,
                accumulated_content=content_buf[0], stream_start=ctx.stream_start,
                is_new_session=ctx.is_new_session, is_one_shot=ctx.is_one_shot,
            )
            return

        # Execute tools and yield results
        logger.info(
            f"Streaming turn {turn}: executing {len(pending_tool_calls)} tool(s) "
            f"for session {ctx.session_id}"
        )
        tool_result_tuples: list[tuple[str, str, str, bool]] = []
        for tc_event in pending_tool_calls:
            raw_name = tc_event.tool_name or ""
            resolved_name = _TOOL_NAME_ALIASES.get(raw_name, raw_name)
            if resolved_name != raw_name:
                logger.info(f"Streaming: normalized tool name '{raw_name}' → '{resolved_name}'")
            tool_call = ToolCall(
                id=tc_event.tool_id or "",
                name=resolved_name,
                input=tc_event.tool_input or {},
            )

            # Yield "running" status so frontend shows spinner
            yield f"data: {StreamingChunk(type='tool_result', tool_id=tool_call.id, tool_status='running').model_dump_json()}\n\n"

            result = await handler.execute(tool_call)
            tool_result_tuples.append(
                (result.tool_use_id, tool_call.name, result.content, result.is_error)
            )

            # Yield completed tool result
            yield f"data: {StreamingChunk(type='tool_result', tool_id=result.tool_use_id, tool_result=result.content, tool_status='error' if result.is_error else 'complete').model_dump_json()}\n\n"

        # Rebuild messages for next turn:
        # 1. Append assistant message with text + tool_use blocks
        assistant_blocks = _build_assistant_content_blocks(turn_text, pending_tool_calls)
        current_messages.append(Message(role="assistant", content=assistant_blocks))

        # 2. Append user message with tool_result blocks
        result_blocks = _build_tool_result_blocks(tool_result_tuples)
        current_messages.append(Message(role="user", content=result_blocks))

    # Reached max turns — yield done with what we have
    logger.warning(f"Streaming: reached max tool turns ({_MAX_TOOL_TURNS}) for session {ctx.session_id}")
    error_chunk = StreamingChunk(type="error", error=f"Tool execution reached maximum turns ({_MAX_TOOL_TURNS})")
    yield f"data: {error_chunk.model_dump_json()}\n\n"


async def stream_completion(
    messages: list[Message],
    model: str,
    provider: str,
    temperature: float,
    session_id: str,
    agent_used: str | None = None,
    model_used: str | None = None,
    fallback_used: bool = False,
    max_tokens: int | None = None,
    db: AsyncSession | None = None,
    user_messages: list[MessageInput] | None = None,
    is_new_session: bool = False,
    is_one_shot: bool = False,
    tools: list[dict[str, object]] | None = None,
    project_id: str | None = None,
) -> AsyncIterator[str]:
    """Stream completion in SSE format.

    When tools are provided and the model requests tool execution, runs a
    tool execution loop: stream → execute tools → yield results → re-stream.

    Yields:
        SSE formatted strings: "data: {json}\n\n"
    """
    adapter = get_adapter(provider)
    content_buf: list[str] = [""]
    stream_kwargs: dict[str, object] = {"tools": tools} if tools else {}
    ctx = _StreamContext(
        session_id=session_id, model=model, provider=provider,
        agent_used=agent_used, model_used=model_used, fallback_used=fallback_used,
        user_messages=user_messages, stream_start=time.monotonic(),
        is_new_session=is_new_session, is_one_shot=is_one_shot,
    )
    yield f"data: {StreamingChunk(type='connected', session_id=session_id).model_dump_json()}\n\n"
    try:
        if tools:
            async for sse in _iter_stream_sse_with_tools(adapter, messages, model, max_tokens, temperature, stream_kwargs, content_buf, ctx, project_id):
                yield sse
        else:
            async for sse in _iter_stream_sse(adapter, messages, model, max_tokens, temperature, stream_kwargs, content_buf, ctx):
                yield sse
    except Exception as e:
        logger.error(f"Streaming error: {e}")
        yield f"data: {StreamingChunk(type='error', error=str(e)).model_dump_json()}\n\n"
    yield "data: [DONE]\n\n"
