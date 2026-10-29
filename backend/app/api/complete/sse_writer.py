"""SSE-wire chunk writer for the completion streaming path.

:class:`SseWriter` formats each chunk of the immutable SSE event protocol
that ``summitflow``, ``portfolio-ai``, and ``vantage`` consume.
:func:`backend.app.api.complete.streaming._emit_events` translates the
universal event stream (``backend/app/llm/stream.py`` plus the tool-loop
overlay events from ``backend/app/llm/tool_loop.py``) into calls on it.

The downstream contract is documented in
``backend/tasks/agent-framework-convergence/downstream-consumers.md``
Section 6 — 9 event types, every event carries a monotonic ``seq: int``,
wire format is ``data: {json}\\n\\n``. **Field names and structure must
not change here without renegotiating the contract.**
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.llm.types import (
    AssistantMessage,
    ImageContent,
    TextContent,
    ToolResultMessage,
)


def _format_sse(payload: dict[str, Any]) -> str:
    """Encode one SSE chunk as ``data: {json}\\n\\n``."""

    return f"data: {json.dumps(payload, default=str)}\n\n"


def tool_result_text(result: ToolResultMessage) -> str:
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

    def connected(
        self, *, model: str | None = None, provider: str | None = None, turn_id: str | None = None
    ) -> str:
        payload: dict[str, Any] = {
            "type": "connected",
            "seq": self.next_seq(),
            "session_id": self.session_id,
        }
        if model is not None:
            payload["model"] = model
        if provider is not None:
            payload["provider"] = provider
        if turn_id is not None:
            payload["turn_id"] = turn_id
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

    def turn_retry(self, attempt: int, max_retries: int, reason: str) -> str:
        return _format_sse(
            {
                "type": "turn_retry",
                "seq": self.next_seq(),
                "attempt": attempt,
                "max_retries": max_retries,
                "reason": reason,
            }
        )

    def context_compacted(self, record: dict[str, Any]) -> str:
        """The tool loop summarized older history before the next model call (sizes, summarizer model and cost)."""
        return _format_sse({"type": "context_compacted", "seq": self.next_seq(), **record})

    def cancel_acknowledged(self) -> str:
        return _format_sse(
            {
                "type": "cancel_acknowledged",
                "seq": self.next_seq(),
                "session_id": self.session_id,
            }
        )

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
        (agent_used, model_used, fallback_used, ...).
        """

        for key, value in meta.items():
            if value is not None:
                self._routing_meta[key] = value


__all__ = ["SseWriter", "tool_result_text"]
