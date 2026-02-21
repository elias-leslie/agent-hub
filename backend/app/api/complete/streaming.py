"""Streaming completion logic for completion API."""

from __future__ import annotations

import asyncio
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

# Default maximum turns for streaming tool execution (configurable per-request)
DEFAULT_MAX_TOOL_TURNS = 15

# Heartbeat interval in seconds — keeps SSE connections alive through proxies
_HEARTBEAT_INTERVAL_S = 15

# Tool retry configuration for transient failures
_TOOL_MAX_RETRIES = 3
_TOOL_RETRY_BASE_DELAY = 2.0  # seconds
_TOOL_RETRY_MAX_DELAY = 30.0  # seconds

# Patterns in tool error output that indicate transient (retriable) failures
_TRANSIENT_ERROR_PATTERNS = (
    "429", "rate limit", "Rate limit",
    "503", "service unavailable", "Service Unavailable",
    "timeout", "timed out", "Timeout", "Timed out",
    "connection refused", "Connection refused",
    "connection reset", "Connection reset",
    "UNAVAILABLE", "RESOURCE_EXHAUSTED",
)

# Registry of active streaming sessions for cooperative cancellation.
# Maps session_id → asyncio.Event (set when cancellation is requested).
_active_streams: dict[str, asyncio.Event] = {}


def register_active_stream(session_id: str) -> asyncio.Event:
    """Register an active stream for cancellation support. Returns the cancel event."""
    event = asyncio.Event()
    _active_streams[session_id] = event
    return event


def cancel_active_stream(session_id: str) -> bool:
    """Signal an active stream to cancel tool execution. Returns True if stream was found."""
    event = _active_streams.get(session_id)
    if event is not None:
        event.set()
        return True
    return False


def _unregister_active_stream(session_id: str) -> None:
    """Remove a stream from the active registry."""
    _active_streams.pop(session_id, None)


def _is_transient_tool_error(error_content: str) -> bool:
    """Check if a tool error result indicates a transient failure worth retrying."""
    return any(pattern in error_content for pattern in _TRANSIENT_ERROR_PATTERNS)


async def _execute_tool_with_retry(
    handler: object,
    tool_call: object,
    max_retries: int = _TOOL_MAX_RETRIES,
) -> object:
    """Execute a tool call with retry for transient failures.

    Retries with exponential backoff when the tool result indicates a transient
    error (429, 503, timeout, connection issues). Non-transient errors and
    successful results are returned immediately.
    """
    result = await handler.execute(tool_call)  # type: ignore[attr-defined]
    for attempt in range(1, max_retries):
        if not result.is_error or not _is_transient_tool_error(result.content):
            return result
        delay = min(_TOOL_RETRY_BASE_DELAY * (2 ** (attempt - 1)), _TOOL_RETRY_MAX_DELAY)
        logger.warning(
            f"Transient tool error (attempt {attempt}/{max_retries}), "
            f"retrying in {delay:.1f}s: {result.content[:200]}"
        )
        await asyncio.sleep(delay)
        result = await handler.execute(tool_call)  # type: ignore[attr-defined]
    return result


def _log_tool_audit(
    session_id: str,
    tool_name: str,
    tool_input: dict[str, object],
    result_content: str,
    is_error: bool,
    duration_ms: int | None,
    sensitivity: str,
    agent_id: str | None,
) -> None:
    """Fire-and-forget audit log for sensitive tool executions.

    Stores a TOOL_AUDIT event in session_events via a background task.
    """
    import asyncio

    async def _store() -> None:
        try:
            from app.db import async_session
            from app.models.session import SessionEventType
            from app.services.event_storage import store_event

            async with async_session() as db:
                await store_event(
                    db=db,
                    session_id=session_id,
                    event_type=SessionEventType.TOOL_AUDIT,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_output={
                        "result": result_content[:2000],
                        "is_error": is_error,
                        "sensitivity": sensitivity,
                    },
                    duration_ms=duration_ms,
                    agent_id=agent_id,
                )
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to store tool audit event: {e}")

    # Fire and forget — don't block the streaming loop
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(_store())
        # Keep reference to prevent premature garbage collection
        _ = task
    except RuntimeError:
        pass


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
    seq: int | None = None,
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
        seq=seq,
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


def _sse_for_simple_event(event: object, content_buf: list[str], ctx: _StreamContext) -> str | None:
    """Return SSE string for content/tool_use/tool_result/error events; None for unknown types."""
    event_type = event.type  # type: ignore[attr-defined]
    if event_type == "content":
        content_buf[0] += event.content or ""  # type: ignore[attr-defined]
        chunk = StreamingChunk(type="content", seq=ctx.next_seq(), content=event.content)  # type: ignore[attr-defined]
        return f"data: {chunk.model_dump_json()}\n\n"
    if event_type == "tool_use":
        chunk = StreamingChunk(
            type="tool_use",
            seq=ctx.next_seq(),
            tool_id=event.tool_id,  # type: ignore[attr-defined]
            tool_name=event.tool_name,  # type: ignore[attr-defined]
            tool_input=event.tool_input,  # type: ignore[attr-defined]
        )
        return f"data: {chunk.model_dump_json()}\n\n"
    if event_type == "tool_result":
        # Adapter already executed this tool (e.g. Claude CLI) — forward to frontend
        chunk = StreamingChunk(
            type="tool_result",
            seq=ctx.next_seq(),
            tool_id=event.tool_id,  # type: ignore[attr-defined]
            tool_result=event.content,  # type: ignore[attr-defined]
            tool_status="complete",
        )
        return f"data: {chunk.model_dump_json()}\n\n"
    if event_type == "error":
        error_chunk = StreamingChunk(type="error", seq=ctx.next_seq(), error=event.error)  # type: ignore[attr-defined]
        return f"data: {error_chunk.model_dump_json()}\n\n"
    return None


class _StreamContext:
    """Holds context needed while iterating stream events."""

    __slots__ = (
        "_seq", "agent_used", "cancel_event", "fallback_used", "is_new_session",
        "is_one_shot", "model", "model_used", "provider", "session_id",
        "stream_start", "user_messages",
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
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        self._seq = 0
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
        self.cancel_event = cancel_event

    def next_seq(self) -> int:
        """Return the next monotonic sequence number."""
        self._seq += 1
        return self._seq


async def _iter_stream_sse(adapter: object, messages: object, model: str, max_tokens: object, temperature: float, stream_kwargs: dict[str, object], content_buf: list[str], ctx: _StreamContext) -> AsyncIterator[str]:
    """Yield SSE strings from adapter stream events (no tool execution)."""
    async for event in adapter.stream(messages=messages, model=model, max_tokens=max_tokens, temperature=temperature, **stream_kwargs):  # type: ignore[attr-defined]
        if event.type == "done":
            yield await _build_done_sse(event=event, session_id=ctx.session_id, model=ctx.model, provider=ctx.provider, agent_used=ctx.agent_used, model_used=ctx.model_used, fallback_used=ctx.fallback_used, user_messages=ctx.user_messages, accumulated_content=content_buf[0], stream_start=ctx.stream_start, is_new_session=ctx.is_new_session, is_one_shot=ctx.is_one_shot, seq=ctx.next_seq())
            continue
        sse = _sse_for_simple_event(event, content_buf, ctx)
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
    max_tool_turns: int = DEFAULT_MAX_TOOL_TURNS,
) -> AsyncIterator[str]:
    """Yield SSE strings with provider-agnostic tool execution loop.

    Adapters emit tool_use events when the model requests tools.  If the
    adapter also emits matching tool_result events (e.g. Claude CLI which
    executes tools natively), those tools are considered resolved and will
    NOT be re-executed.  Only unresolved tool_use events trigger execution
    via DirectToolHandler.

    This makes the loop truly agnostic — it doesn't care which provider
    ran the tools, it only executes what's left unresolved.
    """
    from app.services.tools.base import ToolCall
    from app.services.tools.tool_handler import create_direct_handler

    working_dir = stream_kwargs.get("working_dir")
    handler = create_direct_handler(working_dir=working_dir, project_id=project_id)
    current_messages = list(messages)
    turn = 0

    while turn < max_tool_turns:
        turn += 1
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
            if event.type == "done":
                done_event = event
                break

            if event.type == "tool_use":
                pending_tool_calls.append(event)

            # Adapter already executed this tool — mark as resolved
            if event.type == "tool_result" and event.tool_id:
                resolved_tool_ids.add(event.tool_id)

            # Accumulate text for message rebuilding
            if event.type == "content":
                turn_text += event.content or ""

            sse = _sse_for_simple_event(event, content_buf, ctx)
            if sse is not None:
                yield sse

        if done_event is None:
            # Stream ended without done event (error already yielded by adapter)
            return

        # Filter out tool calls that the adapter already resolved
        unresolved = [tc for tc in pending_tool_calls if tc.tool_id not in resolved_tool_ids]

        if not unresolved:
            yield await _build_done_sse(
                event=done_event, session_id=ctx.session_id,
                model=ctx.model, provider=ctx.provider,
                agent_used=ctx.agent_used, model_used=ctx.model_used,
                fallback_used=ctx.fallback_used, user_messages=ctx.user_messages,
                accumulated_content=content_buf[0], stream_start=ctx.stream_start,
                is_new_session=ctx.is_new_session, is_one_shot=ctx.is_one_shot,
                seq=ctx.next_seq(),
            )
            return

        # Execute unresolved tools
        logger.info(
            f"Streaming turn {turn}: executing {len(unresolved)} tool(s) "
            f"for session {ctx.session_id}"
        )
        tool_result_tuples: list[tuple[str, str, str, bool]] = []
        for tc_event in unresolved:
            # Check for user-initiated cancellation before executing each tool
            if ctx.cancel_event and ctx.cancel_event.is_set():
                logger.info(f"Streaming: user cancelled tool execution for session {ctx.session_id}")
                cancelled_chunk = StreamingChunk(
                    type="cancelled", seq=ctx.next_seq(),
                    session_id=ctx.session_id, provider=ctx.provider, model=ctx.model,
                )
                yield f"data: {cancelled_chunk.model_dump_json()}\n\n"
                return

            tool_name = tc_event.tool_name or ""
            tool_call = ToolCall(
                id=tc_event.tool_id or "",
                name=tool_name,
                input=tc_event.tool_input or {},
            )

            # Yield tool_start so frontend knows execution is beginning
            yield f"data: {StreamingChunk(type='tool_start', seq=ctx.next_seq(), tool_id=tool_call.id, tool_name=tool_name).model_dump_json()}\n\n"

            result = await _execute_tool_with_retry(handler, tool_call)
            tool_result_tuples.append(
                (result.tool_use_id, tool_call.name, result.content, result.is_error)
            )

            # Audit log sensitive tool executions
            from app.services.tools.tool_handler import SENSITIVE_TOOLS

            sensitivity = SENSITIVE_TOOLS.get(tool_name)
            if sensitivity:
                _log_tool_audit(
                    session_id=ctx.session_id,
                    tool_name=tool_name,
                    tool_input=tc_event.tool_input or {},
                    result_content=result.content,
                    is_error=result.is_error,
                    duration_ms=result.duration_ms,
                    sensitivity=sensitivity,
                    agent_id=ctx.agent_used,
                )

            # Yield tool result (also serves as tool_end for backward compatibility)
            yield f"data: {StreamingChunk(type='tool_result', seq=ctx.next_seq(), tool_id=result.tool_use_id, tool_result=result.content, tool_status='error' if result.is_error else 'complete').model_dump_json()}\n\n"

        # Rebuild messages for next turn:
        # 1. Append assistant message with text + tool_use blocks
        assistant_blocks = _build_assistant_content_blocks(turn_text, pending_tool_calls)
        current_messages.append(Message(role="assistant", content=assistant_blocks))

        # 2. Append user message with tool_result blocks
        result_blocks = _build_tool_result_blocks(tool_result_tuples)
        current_messages.append(Message(role="user", content=result_blocks))

    # Reached max turns — yield done with what we have
    logger.warning(f"Streaming: reached max tool turns ({max_tool_turns}) for session {ctx.session_id}")
    error_chunk = StreamingChunk(type="error", seq=ctx.next_seq(), error=f"Tool execution reached maximum turns ({max_tool_turns})")
    yield f"data: {error_chunk.model_dump_json()}\n\n"


async def _with_heartbeat(
    inner: AsyncIterator[str],
    interval: float = _HEARTBEAT_INTERVAL_S,
) -> AsyncIterator[str]:
    """Wrap an SSE iterator with periodic heartbeat comments.

    Emits ``: heartbeat\\n\\n`` when no data flows for ``interval`` seconds,
    keeping the connection alive through reverse proxies and load balancers.
    """
    ait = inner.__aiter__()
    while True:
        try:
            chunk = await asyncio.wait_for(ait.__anext__(), timeout=interval)
            yield chunk
        except TimeoutError:
            yield ": heartbeat\n\n"
        except StopAsyncIteration:
            return


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
    max_tool_turns: int = DEFAULT_MAX_TOOL_TURNS,
    working_dir: str | None = None,
) -> AsyncIterator[str]:
    """Stream completion in SSE format.

    When tools are provided and the model requests tool execution, runs a
    tool execution loop: stream → execute tools → yield results → re-stream.

    Includes automatic heartbeat every 15s to keep connections alive through
    reverse proxies.

    Yields:
        SSE formatted strings: "data: {json}\\n\\n"
    """
    adapter = get_adapter(provider)
    content_buf: list[str] = [""]
    stream_kwargs: dict[str, object] = {"tools": tools} if tools else {}
    if working_dir:
        stream_kwargs["working_dir"] = working_dir
    cancel_event = register_active_stream(session_id)
    ctx = _StreamContext(
        session_id=session_id, model=model, provider=provider,
        agent_used=agent_used, model_used=model_used, fallback_used=fallback_used,
        user_messages=user_messages, stream_start=time.monotonic(),
        is_new_session=is_new_session, is_one_shot=is_one_shot,
        cancel_event=cancel_event,
    )
    yield f"data: {StreamingChunk(type='connected', seq=ctx.next_seq(), session_id=session_id).model_dump_json()}\n\n"
    try:
        if tools:
            inner = _iter_stream_sse_with_tools(adapter, messages, model, max_tokens, temperature, stream_kwargs, content_buf, ctx, project_id, max_tool_turns)
        else:
            inner = _iter_stream_sse(adapter, messages, model, max_tokens, temperature, stream_kwargs, content_buf, ctx)
        async for sse in _with_heartbeat(inner):
            yield sse
    except Exception as e:
        logger.error(f"Streaming error: {e}")
        yield f"data: {StreamingChunk(type='error', seq=ctx.next_seq(), error=str(e)).model_dump_json()}\n\n"
    finally:
        _unregister_active_stream(session_id)
        # Always emit [DONE] so the client knows the stream is complete,
        # even if a BaseException (e.g. CancelledError) propagated through.
        yield "data: [DONE]\n\n"
