"""SSE-wire adapter for :class:`AssistantMessageEvent` streams.

Translates the universal event stream coming out of
``backend/app/llm/stream.py`` (and the tool-loop overlay events from
``backend/app/llm/tool_loop.py``) into the immutable SSE event protocol
that ``summitflow``, ``portfolio-ai``, and ``vantage`` consume.

The downstream contract is documented in
``backend/tasks/agent-framework-convergence/downstream-consumers.md``
Section 6 — 9 event types, every event carries a monotonic ``seq: int``,
wire format is ``data: {json}\\n\\n``. **Field names and structure must
not change here without renegotiating the contract.**
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

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


def _format_sse(payload: dict[str, Any]) -> str:
    """Encode one SSE chunk as ``data: {json}\\n\\n``."""

    return f"data: {json.dumps(payload, default=str)}\n\n"


def _tool_result_text(result: ToolResultMessage) -> str:
    """Flatten a :class:`ToolResultMessage` to a string for the wire.

    Pi-mono allows mixed text/image content in tool results; the wire
    format collapses to text (images are summarized as a placeholder
    note). Downstream consumers parse ``tool_result`` as a string.
    """

    parts: list[str] = []
    for block in result.content:
        if isinstance(block, TextContent):
            parts.append(block.text)
        elif isinstance(block, ImageContent):
            parts.append(f"(image: {block.mime_type})")
    return "\n".join(parts)


def _finish_reason(stop_reason: StopReason) -> str:
    """Map the internal locked enum to the wider HTTP wire vocabulary.

    Per convergence-map.md D2, the internal ``stop_reason`` is one of
    five values; the wire field stays ``str | None`` for backward
    compatibility with existing consumers.
    """

    return stop_reason


@dataclass(slots=True)
class SseWriter:
    """Stateful writer that emits the agent-hub SSE wire protocol."""

    session_id: str
    seq: int = 0
    _routing_meta: dict[str, Any] = field(default_factory=dict)

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq

    # -- discrete event helpers --------------------------------------------

    def connected(self, *, model: str | None = None, provider: str | None = None) -> str:
        payload: dict[str, Any] = {
            "type": "connected",
            "seq": self.next_seq(),
            "session_id": self.session_id,
        }
        if model is not None:
            payload["model"] = model
        if provider is not None:
            payload["provider"] = provider
        return _format_sse(payload)

    def content(self, delta: str) -> str:
        return _format_sse(
            {
                "type": "content",
                "seq": self.next_seq(),
                "content": delta,
                **self._routing_meta,
            }
        )

    def thinking(self, delta: str) -> str:
        return _format_sse(
            {
                "type": "thinking",
                "seq": self.next_seq(),
                "content": delta,
            }
        )

    def tool_use(self, tool_id: str, tool_name: str, tool_input: dict[str, Any]) -> str:
        return _format_sse(
            {
                "type": "tool_use",
                "seq": self.next_seq(),
                "tool_id": tool_id,
                "tool_name": tool_name,
                "tool_input": tool_input,
            }
        )

    def tool_start(self, tool_id: str, tool_name: str) -> str:
        return _format_sse(
            {
                "type": "tool_start",
                "seq": self.next_seq(),
                "tool_id": tool_id,
                "tool_name": tool_name,
            }
        )

    def tool_result(self, tool_id: str, tool_result: str, tool_status: str) -> str:
        return _format_sse(
            {
                "type": "tool_result",
                "seq": self.next_seq(),
                "tool_id": tool_id,
                "tool_result": tool_result,
                "tool_status": tool_status,
            }
        )

    def cancel_acknowledged(self) -> str:
        return _format_sse(
            {
                "type": "cancel_acknowledged",
                "seq": self.next_seq(),
                "session_id": self.session_id,
            }
        )

    def done(self, message: AssistantMessage) -> str:
        payload: dict[str, Any] = {
            "type": "done",
            "seq": self.next_seq(),
            "finish_reason": _finish_reason(message.stop_reason),
            "input_tokens": message.usage.input,
            "output_tokens": message.usage.output,
            "cost_usd": message.usage.cost.total,
            "model": message.model,
            "provider": message.provider,
            "session_id": self.session_id,
        }
        if message.usage.cache_read:
            payload["cache_read_tokens"] = message.usage.cache_read
        if message.usage.cache_write:
            payload["cache_write_tokens"] = message.usage.cache_write
        payload.update(self._routing_meta)
        return _format_sse(payload)

    def _format_done_with_extras(self, extras: dict[str, Any]) -> str:
        """Emit a ``done`` event whose payload is built outside the writer.

        The HTTP route's streaming path computes externally-observable
        fields like ``cost_usd`` and ``model_display_name`` (from the
        catalog + cost estimator) and pushes them in via ``extras``.
        Routing/agent metadata is still merged from
        :meth:`attach_routing`.
        """
        payload: dict[str, Any] = {
            "type": "done",
            "seq": self.next_seq(),
            **self._routing_meta,
            **extras,
        }
        return _format_sse(payload)

    def error(self, message: AssistantMessage) -> str:
        return _format_sse(
            {
                "type": "error",
                "seq": self.next_seq(),
                "error": message.error_message or "Unknown error",
                "model": message.model,
                "provider": message.provider,
                "session_id": self.session_id,
            }
        )

    # -- routing metadata --------------------------------------------------

    def attach_routing(self, **meta: Any) -> None:
        """Attach routing/agent metadata to ``content`` + ``done`` events.

        Used by ``backend/app/routing/`` after the model is resolved
        (agent_used, model_used, fallback_used, routing_mode,
        workload_profile, routing_decision_id, ...).
        """

        for key, value in meta.items():
            if value is not None:
                self._routing_meta[key] = value


async def write_events(
    events: AsyncIterator[ToolLoopEvent],
    writer: SseWriter,
) -> AsyncIterator[str]:
    """Translate a tool-loop / assistant event stream into SSE chunks.

    Yields newline-delimited JSON chunks ready for ``StreamingResponse``.
    The caller is responsible for emitting the initial ``connected``
    chunk (it needs ``model``/``provider`` resolved by the router).
    """

    async for event in events:
        # Tool-loop overlay events (from tool_loop.run()).
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

        # Universal AssistantMessageEvent stream.
        if isinstance(event, TextDeltaEvent):
            if event.delta:
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
        if isinstance(event, DoneEvent):
            yield writer.done(event.message)
            continue
        if isinstance(event, ErrorEvent):
            yield writer.error(event.error)
            continue
        # All other events (start, *_start, *_end, toolcall_start/delta)
        # are partial-message markers without SSE counterparts.


__all__ = ["SseWriter", "write_events"]
