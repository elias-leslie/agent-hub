"""Streaming completion logic for the completion API.

Phase 4 cluster B (per ``CONTINUATION.md``): the HTTP streaming path now
drives :func:`backend.app.api.complete.orchestrator.run_completion_stream`
and :func:`_emit_events` translates the resulting universal events into the
immutable SSE wire protocol, writing each chunk with
:class:`backend.app.api.complete.sse_writer.SseWriter`.

The DB-side persistence (``save_messages_to_db``, citation tracking,
one-shot session cleanup, routing-decision close-out, project cost
record) is preserved verbatim — the wire-facing contract documented in
``backend/tasks/agent-framework-convergence/downstream-consumers.md``
Section 6 cannot drift.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.agent_limits import DEFAULT_AGENTIC_MAX_TURNS
from app.llm.headroom_compress import compression_enabled_for
from app.llm.model_resolver import resolve_llm_model
from app.llm.tool_loop import (
    ToolLoopEvent,
    ToolRunComplete,
    ToolRunError,
    ToolRunStart,
    TurnRetry,
)
from app.llm.types import (
    AssistantMessage,
    DoneEvent,
    ErrorEvent,
    StartEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolCallEndEvent,
)
from app.routing.availability import route_unavailable_reason
from app.routing.registry import get_provider_for_model
from app.services.llm_errors import ProviderError
from app.services.llm_messages import Message, messages_to_dicts

from .event_helpers import TurnTraceStep
from .orchestrator import build_context_from_messages, completion_options, run_completion_stream
from .runtime_usage import accounting_model, aggregate_message_usage, outcome_usage, served_model
from .schemas import MessageInput
from .sse_writer import SseWriter, tool_result_text
from .streaming_context import StreamContext
from .tool_provisioner import build_direct_tool_runner
from .turn_budget import tool_loop_turns

logger = logging.getLogger(__name__)

# Heartbeat interval in seconds — keeps SSE connections alive through proxies
_HEARTBEAT_INTERVAL_S = 15

# Tool execution is bounded only by the shared agentic headroom, as CompletionRequest does.
DEFAULT_MAX_TOOL_TURNS = DEFAULT_AGENTIC_MAX_TURNS


class _EarlyStreamProviderError(RuntimeError):
    """Provider failed before any model output reached the SSE client."""


# Re-export private alias used historically as _StreamContext
_StreamContext = StreamContext


async def _log_stream_cost(
    ctx: StreamContext,
    message: AssistantMessage,
    effective_model: str,
    cost_usd: float,
) -> None:
    """Write the CostLog row for a finished stream, as the non-streaming path does."""
    usage = message.usage
    if not (usage.input or usage.output or usage.cache_read or usage.cache_write):
        return
    try:
        from app.db import async_session
        from app.services.context_tracker import log_token_usage

        async with async_session() as fresh_db:
            await log_token_usage(
                fresh_db,
                ctx.session_id,
                effective_model,
                usage.input,
                usage.output,
                cost_usd,
                cache_read_tokens=int(usage.cache_read or 0),
                cache_write_tokens=int(usage.cache_write or 0),
            )
            await fresh_db.commit()
    except Exception as exc:
        logger.error("Failed to log streaming token usage for %s: %s", ctx.session_id, exc)


async def _record_stream_usage(ctx: StreamContext, message: AssistantMessage) -> float:
    """Record each terminal provider call, including intermediate and failed turns."""
    from app.services.token_counter import estimate_usage_cost

    model = accounting_model(message, ctx.model_used or ctx.model)
    usage = message.usage
    cost = estimate_usage_cost(
        usage.input, usage.output, model,
        cache_read_tokens=usage.cache_read, cache_write_tokens=usage.cache_write,
    ).total_cost_usd
    await _log_stream_cost(ctx, message, model, cost)
    if ctx.project_id and cost > 0:
        from app.services.project_budget import record_project_cost

        await record_project_cost(ctx.project_id, cost)
    return cost


async def _mirror_request_metrics(ctx: StreamContext, message: AssistantMessage) -> None:
    from .streaming_persistence import mirror_stream_request_metrics

    await mirror_stream_request_metrics(ctx, message)


async def _persist_and_build_done_sse(
    *,
    writer: SseWriter,
    ctx: StreamContext,
    message: AssistantMessage,
    accumulated_content: str,
    cost_usd: float | None = None,
    trace: Sequence[TurnTraceStep] = (),
) -> str:
    """Run the same persistence side-effects the legacy path emitted, then return done SSE."""
    from app.constants.catalog import MODEL_CATALOG_BY_ID

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

    effective_model = ctx.model_used or ctx.model
    await save_messages_to_db(
        session_id=ctx.session_id,
        user_messages=ctx.user_messages or [],
        accumulated_content=accumulated_content,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=served_model(message, effective_model),
        agent_used=ctx.agent_used,
        stream_start=ctx.stream_start,
        source_metadata=ctx.source_metadata,
        usage=outcome_usage(message),
        trace=trace,
        thinking_tokens=thinking_tokens,
    )
    await track_citations(ctx.session_id, accumulated_content, ctx.agent_used, ctx.model_used)
    if ctx.is_new_session and ctx.is_one_shot:
        await close_one_shot_session(ctx.session_id)

    if cost_usd is None:
        cost_usd = await _record_stream_usage(ctx, message)

    catalog_entry = MODEL_CATALOG_BY_ID.get(effective_model)
    display_name = catalog_entry.name if catalog_entry else None

    extras: dict[str, object] = {
        "cost_usd": cost_usd,
        "finish_reason": message.stop_reason,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "model": ctx.model,
        "model_used": effective_model,
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


def _tool_result_step(
    event: ToolRunComplete | ToolRunError,
    text: str,
    started_at: dict[str, float],
    *,
    is_error: bool,
) -> TurnTraceStep:
    started = started_at.pop(event.tool_call.id, None)
    return TurnTraceStep(
        kind="tool_result",
        text=text,
        tool_name=event.tool_call.name,
        call_id=event.tool_call.id,
        is_error=is_error,
        duration_ms=None if started is None else int((time.monotonic() - started) * 1000),
    )


async def _emit_events(
    events: AsyncIterator[ToolLoopEvent],
    writer: SseWriter,
    ctx: StreamContext,
    content_buf: list[str],
    attempt_output_started: list[bool] | None = None,
    retry_error_before_output: bool = False,
    tool_loop_active: bool = False,
) -> AsyncIterator[str]:
    """Translate the orchestrator event stream into SSE, accumulating final text.

    When the server-side tool loop is active, each intermediate turn ends with
    a ``toolUse`` DoneEvent; every call records usage, while only the final
    turn persists the answer and emits done with the request totals.
    """
    cancel_event = ctx.cancel_event
    usage_messages: list[AssistantMessage] = []
    total_cost_usd = 0.0
    turn_text_start = len(content_buf[0])
    # What the model thought and which tools it called, stored with the answer so a reopened chat shows it.
    trace: list[TurnTraceStep] = []
    thinking_buf: list[str] = []
    turn_trace_start = 0
    tool_started_at: dict[str, float] = {}

    def flush_thinking() -> None:
        if thinking_buf:
            trace.append(TurnTraceStep(kind="thinking", text="".join(thinking_buf)))
            thinking_buf.clear()

    async for event in events:
        if cancel_event is not None and cancel_event.is_set():
            yield writer.cancel_acknowledged()
            return
        if isinstance(event, StartEvent):
            turn_text_start = len(content_buf[0])
            turn_trace_start = len(trace)
            continue
        if isinstance(event, TurnRetry):
            # The interrupted turn's partial text is void; clients drop it on the same event.
            content_buf[0] = content_buf[0][:turn_text_start]
            del trace[turn_trace_start:]
            thinking_buf.clear()
            yield writer.turn_retry(event.attempt, event.max_retries, event.reason)
            continue
        if isinstance(event, TextDeltaEvent):
            if event.delta:
                if attempt_output_started is not None:
                    attempt_output_started[0] = True
                content_buf[0] += event.delta
                yield writer.content(event.delta)
            continue
        if isinstance(event, ThinkingDeltaEvent):
            if event.delta:
                if attempt_output_started is not None:
                    attempt_output_started[0] = True
                thinking_buf.append(event.delta)
                yield writer.thinking(event.delta)
            continue
        if isinstance(event, ToolCallEndEvent):
            if attempt_output_started is not None:
                attempt_output_started[0] = True
            flush_thinking()
            trace.append(
                TurnTraceStep(
                    kind="tool_use",
                    tool_name=event.tool_call.name,
                    call_id=event.tool_call.id,
                    tool_input=event.tool_call.arguments,
                )
            )
            yield writer.tool_use(
                event.tool_call.id,
                event.tool_call.name,
                event.tool_call.arguments,
            )
            continue
        if isinstance(event, ToolRunStart):
            if attempt_output_started is not None:
                attempt_output_started[0] = True
            tool_started_at[event.tool_call.id] = time.monotonic()
            yield writer.tool_start(event.tool_call.id, event.tool_call.name)
            continue
        if isinstance(event, ToolRunComplete):
            if attempt_output_started is not None:
                attempt_output_started[0] = True
            result_text = tool_result_text(event.result)
            trace.append(_tool_result_step(event, result_text, tool_started_at, is_error=False))
            yield writer.tool_result(
                event.tool_call.id,
                result_text,
                "complete",
            )
            continue
        if isinstance(event, ToolRunError):
            if attempt_output_started is not None:
                attempt_output_started[0] = True
            trace.append(_tool_result_step(event, event.error, tool_started_at, is_error=True))
            yield writer.tool_result(event.tool_call.id, event.error, "error")
            continue
        if isinstance(event, DoneEvent):
            usage_messages.append(event.message)
            total_cost_usd += await _record_stream_usage(ctx, event.message)
            await _mirror_request_metrics(ctx, event.message)
            if tool_loop_active and event.reason == "toolUse":
                continue
            flush_thinking()
            yield await _persist_and_build_done_sse(
                writer=writer,
                ctx=ctx,
                message=aggregate_message_usage(event.message, usage_messages),
                accumulated_content=content_buf[0],
                cost_usd=total_cost_usd,
                trace=trace,
            )
            continue
        if isinstance(event, ErrorEvent):
            await _record_stream_usage(ctx, event.error)
            await _mirror_request_metrics(ctx, event.error)
            if (outcome := outcome_usage(event.error)) is not None:
                from .streaming_persistence import mirror_stream_outcome_error

                await mirror_stream_outcome_error(ctx, event.error, outcome)
            if retry_error_before_output and not bool(
                attempt_output_started and attempt_output_started[0]
            ):
                raise _EarlyStreamProviderError(
                    event.error.error_message or "Provider stream failed before output"
                )
            yield writer.error(event.error)
            continue
        # All other events (start/text_start/text_end/thinking_start/_end/
        # toolcall_start/delta) are partial-message markers without SSE
        # counterparts in the locked downstream contract.


@dataclass(slots=True)
class _PumpFailure:
    error: Exception


_PUMP_DONE = object()


async def _with_heartbeat(
    inner: AsyncIterator[str],
    interval: float = _HEARTBEAT_INTERVAL_S,
) -> AsyncGenerator[str]:
    """Wrap an SSE iterator with heartbeat comments during silence.

    One dedicated task drains ``inner`` for its whole life, so every
    ``__anext__`` (and tool execution inside the loop) runs in the same task;
    the consumer waits on a queue and emits a heartbeat whenever ``interval``
    passes with no chunk. Long tool runs and slow first tokens therefore keep
    proxy connections alive. (The removed Claude Agent SDK broke when
    ``__anext__`` hopped between tasks; providers now run in their own runner
    tasks and feed queues, so a single drain task is safe.)
    """
    queue: asyncio.Queue[object] = asyncio.Queue(maxsize=16)

    async def pump() -> None:
        try:
            async for chunk in inner:
                await queue.put(chunk)
        except Exception as exc:
            await queue.put(_PumpFailure(exc))
            return
        await queue.put(_PUMP_DONE)

    task = asyncio.create_task(pump())
    try:
        while True:
            try:
                async with asyncio.timeout(interval):
                    item = await queue.get()
            except TimeoutError:
                yield ": heartbeat\n\n"
                continue
            if item is _PUMP_DONE:
                return
            if isinstance(item, _PumpFailure):
                raise item.error
            yield cast(str, item)
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


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
    fallback_models: list[str] | None = None,
    turn_id: str | None = None,
) -> AsyncIterator[str]:
    """Stream completion in SSE format via the unified pi-mono pipeline.

    Yields SSE chunks (``data: {json}\\n\\n``). Includes an automatic
    15-second heartbeat to keep connections alive through reverse
    proxies. When tools are provided, the universal tool loop drives the
    multi-turn exchange.

    The caller owns the iteration: the HTTP route drives it from a server-side turn task
    (``app.services.turn_runs``), so a client going away does not reach this generator.
    """
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

    if db is not None and ctx.user_messages:
        from .streaming_persistence import save_turn_prompt_to_db

        # Stored now, not with the answer: a client that opens the session mid-turn must see the prompt.
        if await save_turn_prompt_to_db(session_id, ctx.user_messages, source_metadata, agent_used):
            ctx.user_messages = None

    yield writer.connected(model=model, provider=provider, turn_id=turn_id)
    try:
        context = build_context_from_messages(messages_to_dicts(messages), tools=tools)
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

        candidate_models = [model]
        candidate_models.extend(
            candidate
            for candidate in fallback_models or []
            if candidate not in candidate_models
        )
        primary_failure: str | None = None
        for attempt_index, candidate_model in enumerate(candidate_models):
            candidate_provider = get_provider_for_model(candidate_model)
            attempt_output_started = [False]
            has_later_candidate = attempt_index + 1 < len(candidate_models)
            unavailable = await route_unavailable_reason(candidate_model)
            if unavailable is not None:
                logger.info("Skipping streaming model %s: %s", candidate_model, unavailable)
                primary_failure = primary_failure or f"ProviderError: {unavailable}"
                if not has_later_candidate:
                    raise ProviderError(unavailable, provider=candidate_provider, status_code=503)
                continue
            if attempt_index > 0:
                ctx.model_used = candidate_model
                ctx.fallback_used = True
                _attach_routing(writer, ctx)
                writer.attach_routing(fallback_reason=primary_failure)
                if db is not None:
                    from app.db import async_session

                    from .session_repo import get_or_create_session

                    # The request's own session may be closed by now; the turn outlives the request.
                    async with async_session() as turn_db:
                        await get_or_create_session(
                            turn_db,
                            session_id,
                            project_id or "",
                            candidate_provider,
                            candidate_model,
                            agent_slug=agent_used,
                            requested_provider=provider,
                            requested_model=model,
                        )
                        await turn_db.commit()
            try:
                llm_model = resolve_llm_model(candidate_model, candidate_provider)
                events = run_completion_stream(
                    llm_model,
                    context,
                    options=completion_options(
                        temperature,
                        thinking_level,
                        max_tokens,
                        signal=ctx.cancel_event,
                        session_id=ctx.session_id,
                    ),
                    execute_tools=execute_tools,
                    run_tool=run_tool,
                    max_turns=tool_loop_turns(execute_tools, max_tool_turns),
                    compress_tool_results_enabled=(
                        execute_tools and compression_enabled_for(agent_used)
                    ),
                )
                async for chunk in _with_heartbeat(
                    _emit_events(
                        events,
                        writer,
                        ctx,
                        content_buf,
                        attempt_output_started,
                        has_later_candidate,
                        tool_loop_active=execute_tools,
                    )
                ):
                    yield chunk
                break
            except _EarlyStreamProviderError as exc:
                primary_failure = primary_failure or f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "Streaming model %s failed before output; trying configured fallback",
                    candidate_model,
                )
                if not has_later_candidate:
                    raise
                continue
    except Exception as exc:
        logger.error("Streaming error: %s", exc)
        yield writer.error(_synthetic_error_message(model, provider, str(exc)))
    finally:
        # The turn is over (finished, cancelled or failed); stop any provider request still open.
        if ctx.cancel_event is not None:
            ctx.cancel_event.set()
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
