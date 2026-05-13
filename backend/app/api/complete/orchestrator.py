"""Unified orchestrator that drives the new pi-mono-shaped pipeline.

Phase 3 of the convergence refactor (see
``backend/tasks/agent-framework-convergence/CONTINUATION.md``).

Collapses ``complete_orchestrator.py`` + ``complete_execution.py``
(409 LOC across two files) into one entry point that:

1. Converts the wire-level :class:`CompletionRequest` into a universal
   :class:`backend.app.llm.types.Context` plus a resolved
   :class:`backend.app.llm.types.Model`.
2. Calls :func:`backend.app.llm.stream.stream` for the simple path, or
   :func:`backend.app.llm.tool_loop.run` when ``execute_tools=True``.
3. Translates the resulting :class:`AssistantMessageEvent` stream
   into either a :class:`CompletionResponse` (non-streaming) or the
   immutable SSE wire protocol via
   :class:`backend.app.api.complete.sse_writer.SseWriter`.

The orchestrator is intentionally thin: it does **not** know about
sessions, routing, memory injection, cost persistence, or async
dispatch. Those concerns live in adjacent modules (``session_repo``,
``backend.app.routing``, ``backend.app.memory``, ``services/
cost_tracking.py``, ``workflows/completion.py``) and are composed in
``core.complete_internal``.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app.llm.event_stream import AssistantMessageEventStream
from app.llm.stream import stream as llm_stream
from app.llm.tool_loop import ToolLoopEvent, ToolRunner
from app.llm.tool_loop import run as run_tool_loop
from app.llm.types import (
    AssistantMessage,
    Context,
    ImageContent,
    Message,
    Model,
    SimpleStreamOptions,
    StopReason,
    TextContent,
    Tool,
    UserMessage,
)


@dataclass(slots=True)
class OrchestratorResult:
    """Non-streaming orchestration output."""

    message: AssistantMessage
    turns: int = 1
    tool_calls_count: int = 0


def build_context_from_messages(
    messages: list[dict[str, Any]],
    *,
    system_prompt: str | None = None,
    tools: list[Any] | None = None,
) -> Context:
    """Convert HTTP-wire message dicts into a universal :class:`Context`.

    Accepts the ``CompletionRequest.messages`` shape — a list of
    ``{role, content}`` dicts where content is either a string or a
    list of content-block dicts (with ``type`` discriminator).
    """

    universal_messages: list[Message] = []
    for raw in messages:
        role = raw.get("role")
        content = raw.get("content", "")
        if role == "user":
            universal_messages.append(
                UserMessage(content=_decode_user_content(content), timestamp=int(time.time() * 1000))
            )
        # The pi-mono shape carries the system prompt on
        # Context.system_prompt, not on the messages list. Caller is
        # expected to pass it via the system_prompt argument, but
        # accept role='system' for backward compatibility.
        elif role == "system" and isinstance(content, str) and system_prompt is None:
            system_prompt = content
        # role == "assistant" / "tool" replay paths are handled by the
        # session loader before this function is called. Skipping here
        # keeps the orchestrator focused on its single job.

    return Context(
        messages=universal_messages,
        system_prompt=system_prompt,
        tools=_decode_tools(tools),
    )


def _decode_tools(tools: list[Any] | None) -> list[Tool] | None:
    if not tools:
        return None

    decoded: list[Tool] = []
    for raw in tools:
        if isinstance(raw, Tool):
            decoded.append(raw)
            continue

        if isinstance(raw, dict):
            name = str(raw.get("name", "")).strip()
            description = str(raw.get("description", ""))
            schema = raw.get("input_schema") or raw.get("parameters")
        else:
            name = str(getattr(raw, "name", "")).strip()
            description = str(getattr(raw, "description", ""))
            schema = getattr(raw, "input_schema", None) or getattr(raw, "parameters", None)

        if not name:
            continue
        decoded.append(
            Tool(
                name=name,
                description=description,
                parameters=dict(schema) if isinstance(schema, dict) else {},
            )
        )

    return decoded or None


def _decode_user_content(content: Any) -> str | list[TextContent | ImageContent]:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    blocks: list[TextContent | ImageContent] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            blocks.append(TextContent(text=str(block.get("text", ""))))
        elif block.get("type") == "image":
            source = block.get("source") or {}
            if source.get("type") == "base64":
                blocks.append(
                    ImageContent(
                        data=str(source.get("data", "")),
                        mime_type=str(source.get("media_type", "image/png")),
                    )
                )
    return blocks or [TextContent(text="")]


async def run_completion(
    model: Model[Any],
    context: Context,
    *,
    execute_tools: bool = False,
    run_tool: ToolRunner | None = None,
    options: SimpleStreamOptions | None = None,
    max_turns: int = 32,
) -> OrchestratorResult:
    """Drive the new pipeline to completion (non-streaming).

    With ``execute_tools=False`` this is a single-turn ``stream().result()``.
    With ``execute_tools=True`` the unified
    :func:`backend.app.llm.tool_loop.run` drives the multi-turn loop;
    callers must supply ``run_tool``.
    """

    if execute_tools:
        if run_tool is None:
            raise ValueError("run_tool callback is required when execute_tools=True")
        tool_calls_count = 0
        final: AssistantMessage | None = None
        async for event in run_tool_loop(model, context, run_tool, options, max_turns=max_turns):
            event_type = getattr(event, "type", None)
            if event_type == "tool_run_start":
                tool_calls_count += 1
            elif event_type == "done":
                # The loop yields a DoneEvent per turn; the LAST one
                # wins. Do not break — the loop itself decides when
                # to stop iterating based on stop_reason.
                final = getattr(event, "message", None)
            elif event_type == "error":
                final = getattr(event, "error", None)
        # The tool_loop appends each turn's assistant message to
        # ``context.messages``; the count of AssistantMessages there
        # is the turn count.
        turns = sum(1 for m in context.messages if isinstance(m, AssistantMessage))
        if final is None:
            raise RuntimeError("tool_loop ended without a terminal event")
        return OrchestratorResult(message=final, turns=turns, tool_calls_count=tool_calls_count)

    stream_handle = llm_stream(model, context, options)
    # Drain the stream so all events fire (consumers may attach
    # observers via callbacks before calling us).
    async for _event in stream_handle:
        pass
    final = await stream_handle.result()
    return OrchestratorResult(message=final, turns=1, tool_calls_count=0)


async def run_completion_stream(
    model: Model[Any],
    context: Context,
    *,
    execute_tools: bool = False,
    run_tool: ToolRunner | None = None,
    options: SimpleStreamOptions | None = None,
    max_turns: int = 32,
) -> AsyncIterator[ToolLoopEvent]:
    """Streaming variant: yield each :class:`ToolLoopEvent` as it arrives.

    The HTTP route handler wraps this with
    :func:`backend.app.api.complete.sse_writer.write_events` to emit
    SSE chunks matching the immutable downstream contract.
    """

    if execute_tools:
        if run_tool is None:
            raise ValueError("run_tool callback is required when execute_tools=True")
        async for event in run_tool_loop(model, context, run_tool, options, max_turns=max_turns):
            yield event
        return

    stream_handle: AssistantMessageEventStream = llm_stream(model, context, options)
    async for event in stream_handle:
        yield event


def stop_reason_to_finish_reason(stop_reason: StopReason) -> str:
    """Surface the locked StopReason enum as the wire ``finish_reason`` string.

    The HTTP boundary keeps a wider vocabulary for backward compatibility;
    internal events use the 5-value enum (D2).
    """

    return stop_reason


__all__ = [
    "OrchestratorResult",
    "build_context_from_messages",
    "run_completion",
    "run_completion_stream",
    "stop_reason_to_finish_reason",
]
