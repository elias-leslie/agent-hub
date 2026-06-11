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

The HTTP ``POST /api/complete`` path (``execute_tools=True``) wraps this
loop with the SSE writer in ``backend/app/api/complete/sse_writer.py``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from .headroom_compress import compress_tool_results
from .stream import stream_simple
from .types import (
    AssistantMessage,
    AssistantMessageEvent,
    Context,
    Model,
    SimpleStreamOptions,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)


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


ToolRunEvent = ToolRunStart | ToolRunComplete | ToolRunError
ToolLoopEvent = AssistantMessageEvent | ToolRunEvent

ToolRunner = Callable[[ToolCall], Awaitable[ToolResultMessage]]


@dataclass(slots=True)
class ToolLoopResult:
    """Final result of :func:`run`. Mirrors pi-mono's loop return."""

    message: AssistantMessage
    turns: int
    tool_calls_count: int
    aborted: bool = False
    errored: bool = False


async def run(
    model: Model[Any],
    context: Context,
    run_tool: ToolRunner,
    options: SimpleStreamOptions | None = None,
    max_turns: int = 32,
    compress_tool_results_enabled: bool = False,
    compression_stats_sink: dict[str, int] | None = None,
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

        stream_handle = stream_simple(model, context, options)

        async for event in stream_handle:
            yield event

        final = await stream_handle.result()
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

        for tool_call in tool_calls:
            tool_calls_count += 1
            yield ToolRunStart(tool_call=tool_call)

            try:
                result = await run_tool(tool_call)
            except Exception as exc:
                error_msg = str(exc) or type(exc).__name__
                # Build a synthetic error result so the next turn sees it.
                import time as _time

                result = ToolResultMessage(
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    content=[],
                    is_error=True,
                    timestamp=int(_time.time() * 1000),
                )
                yield ToolRunError(tool_call=tool_call, result=result, error=error_msg)
            else:
                yield ToolRunComplete(tool_call=tool_call, result=result)

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
    stream_handle = stream_simple(model, context, options)
    async for event in stream_handle:
        yield event
    context.messages.append(await stream_handle.result())


__all__ = [
    "ToolLoopEvent",
    "ToolLoopResult",
    "ToolRunComplete",
    "ToolRunError",
    "ToolRunEvent",
    "ToolRunStart",
    "ToolRunner",
    "run",
]
