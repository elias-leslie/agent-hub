"""Unified tool loop.

NEW-REQUIREMENT (convergence-map.md C5): agent-hub runs tool execution
server-side when ``execute_tools=True`` is set on the HTTP request. This
module is the single canonical tool-loop pipeline. It replaces:

* ``api/complete/tool_handlers.py``, ``tool_handler_utils.py``,
  ``multi_turn_executor.py``, ``multi_turn_loop.py``,
  ``multi_turn_helpers.py`` (sync tool loop, 5 files);
* ``api/complete/streaming_tool_loop.py``,
  ``streaming_tool_executor.py``, ``streaming_tool_messages.py``,
  ``streaming_runtime_session.py`` (streaming tool loop, 4 files).

It consumes the universal :class:`AssistantMessageEvent` stream, takes a
caller-supplied async ``run_tool`` callback (the agent-hub
``backend/app/services/tools/`` registry plugs in here), and yields a
mixed stream of ``AssistantMessageEvent | ToolRunEvent``.

The HTTP ``POST /api/complete`` streaming path (``execute_tools=True``)
translates this loop's events into SSE in
``backend/app/api/complete/streaming.py`` (``_emit_events``).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any, Literal

from .headroom_compress import compress_tool_results
from .stream import stream_simple
from .types import (
    AssistantMessage,
    AssistantMessageEvent,
    Context,
    ErrorEvent,
    Model,
    SimpleStreamOptions,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from .utils.outcomes import outcome_of
from .utils.retry import retry_budget, retry_delay

# Per-turn and per-tool timing at DEBUG (LOG_LEVELS=app.llm=DEBUG): what a slow run spent its time on.
logger = logging.getLogger(__name__)

@dataclass(slots=True)
class ToolRunStart:
    """Emitted just before a tool starts executing."""

    tool_call: ToolCall
    type: Literal["tool_run_start"] = "tool_run_start"


@dataclass(slots=True)
class ToolRunComplete:
    """Emitted when a tool finishes successfully."""

    tool_call: ToolCall
    result: ToolResultMessage
    type: Literal["tool_run_complete"] = "tool_run_complete"


@dataclass(slots=True)
class ToolRunError:
    """Emitted when a tool raises (the error is also persisted as a
    ``ToolResultMessage`` with ``is_error=True``)."""

    tool_call: ToolCall
    result: ToolResultMessage
    error: str
    type: Literal["tool_run_error"] = "tool_run_error"


@dataclass(slots=True)
class TurnRetry:
    """A turn was interrupted and is being re-run from the same context.

    Everything streamed since this turn's ``start`` event is void: consumers drop that partial text.
    """

    attempt: int
    max_retries: int
    reason: str
    delay_s: float
    type: Literal["turn_retry"] = "turn_retry"


ToolRunEvent = ToolRunStart | ToolRunComplete | ToolRunError
ToolLoopEvent = AssistantMessageEvent | ToolRunEvent | TurnRetry

ToolRunner = Callable[[ToolCall], Awaitable[ToolResultMessage]]


@dataclass(slots=True)
class ToolLoopResult:
    """Final result of :func:`run`. Mirrors pi-mono's loop return."""

    message: AssistantMessage
    turns: int
    tool_calls_count: int
    aborted: bool = False
    errored: bool = False


ParallelSafe = Callable[[ToolCall], bool]


def _batches(calls: list[ToolCall], is_parallel_safe: ParallelSafe | None) -> list[list[ToolCall]]:
    """Group consecutive parallel-safe calls; every other call is its own serial batch."""
    batches: list[list[ToolCall]] = []
    previous_safe = False
    for call in calls:
        safe = bool(is_parallel_safe and is_parallel_safe(call))
        if safe and previous_safe:
            batches[-1].append(call)
        else:
            batches.append([call])
        previous_safe = safe
    return batches


async def _run_one(run_tool: ToolRunner, tool_call: ToolCall) -> tuple[ToolResultMessage, str | None]:
    """Run one tool; a raise becomes an error result the next turn can see."""
    start = time.monotonic()
    try:
        result = await run_tool(tool_call)
        logger.debug("tool %s took %.2fs", tool_call.name, time.monotonic() - start)
        return result, None
    except Exception as exc:
        error_msg = str(exc) or type(exc).__name__
        logger.debug("tool %s failed after %.2fs: %s", tool_call.name, time.monotonic() - start, error_msg)
        return (
            ToolResultMessage(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                content=[TextContent(text=f"Tool execution failed: {error_msg}")],
                is_error=True,
                timestamp=int(time.time() * 1000),
            ),
            error_msg,
        )


async def _turn(
    model: Model[Any],
    context: Context,
    options: SimpleStreamOptions | None,
    sink: list[AssistantMessage],
) -> AsyncIterator[ToolLoopEvent]:
    """One model turn. An interrupted stream (dead connection, stall, runaway tool call) is re-run from the
    same context after a backoff, up to the retry budget; the partial message never reaches ``context``.

    The provider is told not to retry on its own (``max_retries=0``), so this is the single place the
    budget is spent. The turn's final message is appended to ``sink``.
    """
    retries = retry_budget(options)
    attempt_options = replace(options or SimpleStreamOptions(), max_retries=0)
    for attempt in range(retries + 1):
        stream_handle = stream_simple(model, context, attempt_options)
        interrupted: ErrorEvent | None = None
        async for event in stream_handle:
            if isinstance(event, ErrorEvent) and attempt < retries:
                outcome = outcome_of(event.error)
                if outcome is not None and outcome.kind == "interrupted":
                    interrupted = event
                    continue
            yield event
        if interrupted is None:
            sink.append(await stream_handle.result())
            return
        reason = interrupted.error.error_message or "interrupted"
        delay = retry_delay(attempt)
        logger.warning("turn interrupted (%s); retry %d/%d in %.1fs", reason, attempt + 1, retries, delay)
        yield TurnRetry(attempt=attempt + 1, max_retries=retries, reason=reason, delay_s=delay)
        await asyncio.sleep(delay)


async def run(
    model: Model[Any],
    context: Context,
    run_tool: ToolRunner,
    options: SimpleStreamOptions | None = None,
    max_turns: int = 32,
    compress_tool_results_enabled: bool = False,
    compression_stats_sink: dict[str, int] | None = None,
    is_parallel_safe: ParallelSafe | None = None,
) -> AsyncIterator[ToolLoopEvent]:
    """Run the multi-turn tool loop.

    Iterates over the universal event stream from
    :func:`backend.app.llm.stream.stream_simple` and, when a turn ends
    with ``stop_reason == "toolUse"``, drives ``run_tool`` per tool call,
    appends ``ToolResultMessage``s to ``context.messages``, and starts
    the next turn. Stops on the first non-``toolUse`` terminal or when
    ``max_turns`` is exhausted.

    Yields:
        Each :class:`AssistantMessageEvent` from the provider, plus
        :class:`ToolRunStart` / :class:`ToolRunComplete` /
        :class:`ToolRunError` events around tool execution.
    """

    turns = 0
    tool_calls_count = 0

    while turns < max_turns:
        turns += 1

        # Compress accumulated tool-result text before the next model call when
        # the caller resolved the per-agent gate to ON (off by default). CPU-
        # bound, so run off the event loop. Already-compressed blocks are
        # skipped, so per-turn cost is bounded by the newest tool outputs.
        if compress_tool_results_enabled:
            loop = asyncio.get_running_loop()
            context.messages, turn_stats = await loop.run_in_executor(
                None, compress_tool_results, context.messages, model.id
            )
            if compression_stats_sink is not None:
                for key in ("blocks_compressed", "tokens_before", "tokens_after"):
                    compression_stats_sink[key] = compression_stats_sink.get(key, 0) + int(
                        turn_stats.get(key, 0)
                    )

        turn_start = time.monotonic()
        sunk: list[AssistantMessage] = []
        async for event in _turn(model, context, options, sunk):
            yield event
        final = sunk[0]
        logger.debug(
            "turn %d model_s=%.2f stop=%s tool_calls=%d output_tokens=%d",
            turns, time.monotonic() - turn_start, final.stop_reason,
            sum(isinstance(b, ToolCall) for b in final.content), final.usage.output,
        )
        # Each turn's final assistant message becomes part of the context
        # for the next turn. Errored/aborted messages are still appended
        # so transform_messages can decide what to replay.
        context.messages.append(final)

        if final.stop_reason == "aborted":
            return
        if final.stop_reason == "error":
            return
        if final.stop_reason != "toolUse":
            return

        tool_calls = [b for b in final.content if isinstance(b, ToolCall)]
        if not tool_calls:
            # Provider claimed toolUse but no tool call parsed (observed:
            # kimi ending turn 1 with empty content — the user saw an empty
            # reply). Nudge the model to retry or answer directly; max_turns
            # still bounds the loop.
            import time as _time

            context.messages.append(
                UserMessage(
                    content=(
                        "Your last response ended with a tool-use stop reason "
                        "but contained no parseable tool call. Retry the tool "
                        "call with valid arguments, or answer the user "
                        "directly without tools."
                    ),
                    timestamp=int(_time.time() * 1000),
                )
            )
            continue

        parallel_safe = is_parallel_safe or getattr(run_tool, "is_parallel_safe", None)
        for batch in _batches(tool_calls, parallel_safe):
            tool_calls_count += len(batch)
            for tool_call in batch:
                yield ToolRunStart(tool_call=tool_call)

            # A batch is one mutating call, or a run of consecutive parallel-safe calls
            # (read-only tools) that execute concurrently. Results land in call order.
            outcomes = await asyncio.gather(*(_run_one(run_tool, call) for call in batch))
            for tool_call, (result, error_msg) in zip(batch, outcomes, strict=True):
                if error_msg is None:
                    yield ToolRunComplete(tool_call=tool_call, result=result)
                else:
                    yield ToolRunError(tool_call=tool_call, result=result, error=error_msg)
                context.messages.append(result)

    # max_turns exhausted while the model still wanted tools (every other
    # exit returns inside the loop). Without this, the caller's "final"
    # message is tool-call narration or empty content. Run one last turn
    # instructing the model to answer from the results it already has.
    # Tools stay in the context — providers reject tool-bearing history
    # without tool definitions — but nothing further is executed, so the
    # loop stays bounded at max_turns + 1.
    import time as _time

    context.messages.append(
        UserMessage(
            content=(
                "Tool budget exhausted. Answer the user's question now using "
                "the tool results already collected. Do not request any more "
                "tools."
            ),
            timestamp=int(_time.time() * 1000),
        )
    )
    sunk = []
    async for event in _turn(model, context, options, sunk):
        yield event
    context.messages.append(sunk[0])


__all__ = [
    "ParallelSafe",
    "ToolLoopEvent",
    "ToolLoopResult",
    "ToolRunComplete",
    "ToolRunError",
    "ToolRunEvent",
    "ToolRunStart",
    "ToolRunner",
    "TurnRetry",
    "run",
]
