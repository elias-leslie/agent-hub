"""The live streaming translator emits the downstream SSE event contract.

``stream_completion`` translates the orchestrator event stream through
``streaming._emit_events``. These tests pin the event order, tool fields and
monotonic ``seq`` from
``backend/tasks/agent-framework-convergence/downstream-consumers.md`` Section 6
on that live path.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.api.complete.sse_writer import SseWriter
from app.api.complete.streaming import _attach_routing, _emit_events
from app.llm import tool_loop
from app.llm.tool_loop import ToolLoopEvent
from app.llm.types import (
    AssistantMessage,
    DoneEvent,
    StartEvent,
    StopReason,
    TextContent,
    TextDeltaEvent,
    ToolCall,
    ToolCallEndEvent,
    ToolResultMessage,
    Usage,
)
from tests.api.stream_test_support import make_stream_ctx, patched_done_persistence
from tests.model_ids import CLAUDE_SONNET


def _message(content: list[Any], stop_reason: StopReason, usage: Usage) -> AssistantMessage:
    return AssistantMessage(
        content=content,
        api="anthropic-messages",
        provider="claude",
        model=CLAUDE_SONNET,
        usage=usage,
        stop_reason=stop_reason,
        timestamp=0,
    )


async def _emit(events: AsyncIterator[ToolLoopEvent], session_id: str) -> list[dict[str, Any]]:
    ctx = make_stream_ctx(session_id)
    writer = SseWriter(session_id=session_id)
    _attach_routing(writer, ctx)
    chunks: list[dict[str, Any]] = []
    with patched_done_persistence():
        async for raw in _emit_events(events, writer, ctx, [""]):
            assert raw.startswith("data: ")
            assert raw.endswith("\n\n")
            chunks.append(json.loads(raw[len("data: ") : -2]))
    return chunks


def _assert_seq_strictly_increasing(chunks: list[dict[str, Any]]) -> None:
    seqs = [c["seq"] for c in chunks]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)


@pytest.mark.asyncio
async def test_emit_events_surfaces_tool_round_trip_in_contract_order() -> None:
    tool_call = ToolCall(id="toolu_1", name="echo", arguments={"text": "x"})
    msg_tool = _message([tool_call], "toolUse", Usage(input=10, output=2, total_tokens=12))
    msg_done = _message([TextContent(text="hi")], "stop", Usage(input=12, output=1, total_tokens=13))

    async def events() -> AsyncIterator[ToolLoopEvent]:
        yield TextDeltaEvent(content_index=0, delta="hi", partial=msg_done)
        yield ToolCallEndEvent(content_index=0, tool_call=tool_call, partial=msg_tool)
        yield tool_loop.ToolRunStart(tool_call=tool_call)
        yield tool_loop.ToolRunComplete(
            tool_call=tool_call,
            result=ToolResultMessage(
                tool_call_id="toolu_1",
                tool_name="echo",
                content=[TextContent(text="x")],
                is_error=False,
                timestamp=0,
            ),
        )
        yield DoneEvent(reason="stop", message=msg_done)

    chunks = await _emit(events(), "sess-1")

    assert [c["type"] for c in chunks] == ["content", "tool_use", "tool_start", "tool_result", "done"]
    assert chunks[0]["content"] == "hi"
    assert (chunks[1]["tool_id"], chunks[1]["tool_name"]) == ("toolu_1", "echo")
    assert chunks[1]["tool_input"] == {"text": "x"}
    assert (chunks[2]["tool_id"], chunks[2]["tool_name"]) == ("toolu_1", "echo")
    assert chunks[3]["tool_id"] == "toolu_1"
    assert chunks[3]["tool_status"] == "complete"
    assert chunks[3]["tool_result"] == "x"
    assert chunks[4]["finish_reason"] == "stop"
    assert chunks[4]["session_id"] == "sess-1"
    _assert_seq_strictly_increasing(chunks)


@pytest.mark.asyncio
async def test_emit_events_reports_a_failed_tool_run_as_an_error_result() -> None:
    tool_call = ToolCall(id="toolu_err", name="echo", arguments={})
    msg_done = _message([TextContent(text="recovered")], "stop", Usage(input=3, output=1, total_tokens=4))

    async def events() -> AsyncIterator[ToolLoopEvent]:
        yield tool_loop.ToolRunStart(tool_call=tool_call)
        yield tool_loop.ToolRunError(
            tool_call=tool_call,
            result=ToolResultMessage(
                tool_call_id="toolu_err",
                tool_name="echo",
                content=[TextContent(text="permission denied")],
                is_error=True,
                timestamp=0,
            ),
            error="permission denied",
        )
        yield DoneEvent(reason="stop", message=msg_done)

    chunks = await _emit(events(), "sess-err")

    assert [c["type"] for c in chunks] == ["tool_start", "tool_result", "done"]
    assert chunks[1]["tool_id"] == "toolu_err"
    assert chunks[1]["tool_status"] == "error"
    assert chunks[1]["tool_result"] == "permission denied"
    _assert_seq_strictly_increasing(chunks)


@pytest.mark.asyncio
async def test_emit_events_persists_a_refused_attempt_with_its_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.complete import streaming, streaming_persistence
    from app.llm.types import ErrorEvent
    from app.llm.utils.outcomes import ProviderOutcome, record_outcome

    refused = _message([], "error", Usage())
    refused.error_message = "Claude refused the request: safeguards flagged it (cyber)"
    record_outcome(refused, ProviderOutcome(kind="refused", requested_model=CLAUDE_SONNET, category="cyber"))
    stored: list[tuple[str | None, dict[str, object]]] = []

    async def no_usage(_ctx: object, _message: AssistantMessage) -> float:
        return 0.0

    async def capture(_ctx: object, message: AssistantMessage, usage: dict[str, object]) -> None:
        stored.append((message.error_message, usage))

    monkeypatch.setattr(streaming, "_record_stream_usage", no_usage)
    monkeypatch.setattr(streaming_persistence, "mirror_stream_outcome_error", capture)

    async def events() -> AsyncIterator[ToolLoopEvent]:
        yield ErrorEvent(reason="error", error=refused)

    chunks = await _emit(events(), "sess-refused")

    assert [c["type"] for c in chunks] == ["error"]
    assert stored == [(
        refused.error_message,
        {"provider_outcome": {"kind": "refused", "requested_model": CLAUDE_SONNET, "category": "cyber"}},
    )]


@pytest.mark.asyncio
async def test_emit_events_announces_a_turn_retry_and_drops_the_voided_text() -> None:
    msg = _message([TextContent(text="ok")], "stop", Usage(input=1, output=1, total_tokens=2))
    buf = ["earlier "]

    async def events() -> AsyncIterator[ToolLoopEvent]:
        yield StartEvent(partial=msg)
        yield TextDeltaEvent(content_index=0, delta="half", partial=msg)
        yield tool_loop.TurnRetry(attempt=1, max_retries=2, reason="no progress", delay_s=0.5)
        yield StartEvent(partial=msg)
        yield TextDeltaEvent(content_index=0, delta="ok", partial=msg)
        yield DoneEvent(reason="stop", message=msg)

    writer = SseWriter(session_id="sess-retry")
    _attach_routing(writer, make_stream_ctx("sess-retry"))
    chunks = []
    with patched_done_persistence():
        async for raw in _emit_events(events(), writer, make_stream_ctx("sess-retry"), buf):
            chunks.append(json.loads(raw[len("data: ") : -2]))

    assert [c["type"] for c in chunks] == ["content", "turn_retry", "content", "done"]
    assert (chunks[1]["attempt"], chunks[1]["max_retries"], chunks[1]["reason"]) == (1, 2, "no progress")
    assert buf[0] == "earlier ok"
