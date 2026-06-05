"""Streaming completion logic for the completion API.

Phase 4 cluster B (per ``CONTINUATION.md``): the HTTP streaming path now
drives :func:`backend.app.api.complete.orchestrator.run_completion_stream`
and translates the resulting universal events into the immutable SSE wire
protocol via :class:`backend.app.api.complete.sse_writer.SseWriter`.

The DB-side persistence (``save_messages_to_db``, citation tracking,
one-shot session cleanup, routing-decision close-out, project cost
record) is preserved verbatim — the wire-facing contract documented in
``backend/tasks/agent-framework-convergence/downstream-consumers.md``
Section 6 cannot drift.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.model_resolver import resolve_llm_model
from app.llm.tool_loop import (
    ToolLoopEvent,
    ToolRunComplete,
    ToolRunError,
    ToolRunStart,
)
from app.llm.types import (
    AssistantMessage,
    DoneEvent,
    ErrorEvent,
    ImageContent,
    StopReason,
    TextContent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolCallEndEvent,
    ToolResultMessage,
)
from app.services.llm_messages import Message

from .orchestrator import build_context_from_messages, run_completion_stream
from .schemas import MessageInput
from .sse_writer import SseWriter
from .streaming_context import StreamContext
from .tool_provisioner import build_direct_tool_runner

logger = logging.getLogger(__name__)

# Heartbeat interval in seconds — keeps SSE connections alive through proxies
_HEARTBEAT_INTERVAL_S = 15

# Match CompletionRequest.max_turns default; the shared tool-budget resolver
# lifts low values when tools are actually enabled.
DEFAULT_MAX_TOOL_TURNS = 1

# Re-export private alias used historically as _StreamContext
_StreamContext = StreamContext


def _messages_to_dicts(messages: list[Message]) -> list[dict[str, object]]:
    """Translate adapter ``Message`` rows to ``{role, content}`` dicts."""
    return [{"role": m.role, "content": m.content} for m in messages]


def _tool_result_text(result: ToolResultMessage) -> str:
    parts: list[str] = []
    for block in result.content:
        if isinstance(block, TextContent):
            parts.append(block.text)
        elif isinstance(block, ImageContent):
            parts.append(f"(image: {block.mime_type})")
    return "\n".join(parts)


def _finish_reason(stop_reason: StopReason) -> str:
    return stop_reason


async def _persist_and_build_done_sse(
    *,
    writer: SseWriter,
    ctx: StreamContext,
    message: AssistantMessage,
    accumulated_content: str,
) -> str:
    """Run the same persistence side-effects the legacy path emitted, then return done SSE."""
    from app.constants.catalog import MODEL_CATALOG_BY_ID
    from app.services.token_counter import estimate_cost

    from .streaming_persistence import (
        _track_citations as track_citations,
    )
    from .streaming_persistence import (
        close_one_shot_session,
        save_messages_to_db,
    )

    input_tokens = message.usage.input
    output_tokens = message.usage.output
    thinking_tokens = next(
        (
            getattr(c, "thinking_tokens", None)
            for c in message.content
            if getattr(c, "type", None) == "thinking"
        ),
        None,
    )

    await save_messages_to_db(
        session_id=ctx.session_id,
        user_messages=ctx.user_messages or [],
        accumulated_content=accumulated_content,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=ctx.model,
        agent_used=ctx.agent_used,
        stream_start=ctx.stream_start,
        source_metadata=ctx.source_metadata,
    )
    await track_citations(ctx.session_id, accumulated_content, ctx.agent_used, ctx.model_used)
    if ctx.is_new_session and ctx.is_one_shot:
        await close_one_shot_session(ctx.session_id)

    cost = estimate_cost(input_tokens, output_tokens, ctx.model)
    if ctx.project_id and cost.total_cost_usd > 0:
        from app.services.project_budget import record_project_cost

        await record_project_cost(ctx.project_id, cost.total_cost_usd)

    model_id = ctx.model_used or ctx.model
    catalog_entry = MODEL_CATALOG_BY_ID.get(model_id)
    display_name = catalog_entry.name if catalog_entry else None

    extras: dict[str, object] = {
        "cost_usd": cost.total_cost_usd,
        "finish_reason": _finish_reason(message.stop_reason),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "model": ctx.model,
        "provider": ctx.provider,
        "session_id": ctx.session_id,
    }
    if message.usage.cache_read:
        extras["cache_read_tokens"] = message.usage.cache_read
    if message.usage.cache_write:
        extras["cache_write_tokens"] = message.usage.cache_write
    if thinking_tokens:
        extras["thinking_tokens"] = thinking_tokens
    if display_name:
        extras["model_display_name"] = display_name

    return writer._format_done_with_extras(extras)


def _attach_routing(writer: SseWriter, ctx: StreamContext) -> None:
    writer.attach_routing(
        model=ctx.model,
        provider=ctx.provider,
        agent_used=ctx.agent_used,
        model_used=ctx.model_used,
        fallback_used=ctx.fallback_used if ctx.agent_used else None,
    )


async def _emit_events(
    events: AsyncIterator[ToolLoopEvent],
    writer: SseWriter,
    ctx: StreamContext,
    content_buf: list[str],
) -> AsyncIterator[str]:
    """Translate the orchestrator event stream into SSE, accumulating final text."""
    cancel_event = ctx.cancel_event
    async for event in events:
        if cancel_event is not None and cancel_event.is_set():
            yield writer.cancel_acknowledged()
            return
        if isinstance(event, TextDeltaEvent):
            if event.delta:
                content_buf[0] += event.delta
                yield writer.content(event.delta)
            continue
        if isinstance(event, ThinkingDeltaEvent):
            if event.delta:
                yield writer.thinking(event.delta)
            continue
        if isinstance(event, ToolCallEndEvent):
            yield writer.tool_use(
                event.tool_call.id,
                event.tool_call.name,
                event.tool_call.arguments,
            )
            continue
        if isinstance(event, ToolRunStart):
            yield writer.tool_start(event.tool_call.id, event.tool_call.name)
            continue
        if isinstance(event, ToolRunComplete):
            yield writer.tool_result(
                event.tool_call.id,
                _tool_result_text(event.result),
                "complete",
            )
            continue
        if isinstance(event, ToolRunError):
            yield writer.tool_result(event.tool_call.id, event.error, "error")
            continue
        if isinstance(event, DoneEvent):
            yield await _persist_and_build_done_sse(
                writer=writer,
                ctx=ctx,
                message=event.message,
                accumulated_content=content_buf[0],
            )
            continue
        if isinstance(event, ErrorEvent):
            yield writer.error(event.error)
            continue
        # All other events (start/text_start/text_end/thinking_start/_end/
        # toolcall_start/delta) are partial-message markers without SSE
        # counterparts in the locked downstream contract.


async def _with_heartbeat(
    inner: AsyncIterator[str],
    interval: float = _HEARTBEAT_INTERVAL_S,
) -> AsyncIterator[str]:
    """Wrap an SSE iterator with periodic heartbeat comments.

    Iterates the inner generator directly (same task) to avoid corrupting
    provider SDK task-local cancel scopes. Wrapping ``__anext__`` in a
    separate task (via ``asyncio.ensure_future`` or a drain task) can leave
    cancellation cleanup spinning at 100% CPU.
    """
    last_yield = time.monotonic()
    async for chunk in inner:
        now = time.monotonic()
        while now - last_yield >= interval:
            yield ": heartbeat\n\n"
            last_yield += interval
        yield chunk
        last_yield = time.monotonic()


async def stream_completion(
    messages: list[Message],
    model: str,
    provider: str,
    temperature: float,
    session_id: str,
    thinking_level: str | None = None,
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
    source_metadata: dict[str, object] | None = None,
) -> AsyncIterator[str]:
    """Stream completion in SSE format via the unified pi-mono pipeline.

    Yields SSE chunks (``data: {json}\\n\\n``). Includes an automatic
    15-second heartbeat to keep connections alive through reverse
    proxies. When tools are provided, the universal tool loop drives the
    multi-turn exchange.
    """
    del max_tokens  # Universal pipeline derives max_tokens from the catalog.
    del temperature  # Threaded via SimpleStreamOptions when needed.

    ctx = StreamContext.open(
        session_id=session_id,
        model=model,
        provider=provider,
        agent_used=agent_used,
        model_used=model_used,
        fallback_used=fallback_used,
        user_messages=user_messages,
        stream_start=time.monotonic(),
        is_new_session=is_new_session,
        is_one_shot=is_one_shot,
        project_id=project_id,
        source_metadata=source_metadata,
    )
    writer = SseWriter(session_id=session_id)
    _attach_routing(writer, ctx)
    content_buf: list[str] = [""]

    yield writer.connected(model=model, provider=provider)
    try:
        llm_model = resolve_llm_model(model, provider)
        context = build_context_from_messages(_messages_to_dicts(messages), tools=tools)
        execute_tools = bool(tools)
        run_tool = (
            build_direct_tool_runner(
                working_dir=working_dir,
                project_id=project_id,
                session_id=session_id,
                agent_slug=agent_used,
            )
            if execute_tools
            else None
        )

        events = run_completion_stream(
            llm_model,
            context,
            execute_tools=execute_tools,
            run_tool=run_tool,
            max_turns=max(max_tool_turns, 1) if execute_tools else 1,
        )
        async for chunk in _with_heartbeat(_emit_events(events, writer, ctx, content_buf)):
            yield chunk
    except Exception as exc:
        logger.error("Streaming error: %s", exc)
        yield writer.error(_synthetic_error_message(model, provider, str(exc)))
    finally:
        ctx.close()
        yield "data: [DONE]\n\n"


def _synthetic_error_message(model: str, provider: str, error: str) -> AssistantMessage:
    """Build a minimal AssistantMessage carrying an error for the wire."""
    from app.llm.types import Usage

    return AssistantMessage(
        content=[],
        api="",
        provider=provider,
        model=model,
        usage=Usage(),
        stop_reason="error",
        timestamp=int(time.time() * 1000),
        error_message=error,
    )
