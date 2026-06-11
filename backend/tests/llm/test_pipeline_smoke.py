"""End-to-end smoke test for the new ``backend/app/llm/`` pipeline.

Verifies, without hitting any real network, that:

1. The universal types instantiate.
2. The Anthropic provider registers under ``"anthropic-messages"``.
3. The :class:`AssistantMessageEventStream` queueing + result-resolution works.
4. The tool-loop drives a fake provider through one tool round trip
   and emits the expected ``ToolRunStart`` / ``ToolRunComplete`` events.
5. The SSE writer turns a mixed event stream into wire chunks matching
   the immutable contract in
   ``backend/tasks/agent-framework-convergence/downstream-consumers.md``
   Section 6.

These are deliberately offline smoke tests. The "real Anthropic API"
smoke test referenced in ``CONTINUATION.md`` item 13 lives separately
under ``tests/integration/`` so it can be skipped without a key.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.api.complete.sse_writer import SseWriter, write_events
from app.llm import tool_loop
from app.llm.api_registry import get_api_provider
from app.llm.event_stream import AssistantMessageEventStream
from app.llm.providers import anthropic as anthropic_provider  # noqa: F401 — triggers registration
from app.llm.types import (
    AssistantMessage,
    Context,
    DoneEvent,
    Model,
    ModelCost,
    SimpleStreamOptions,
    StartEvent,
    StopReason,
    TextContent,
    TextDeltaEvent,
    TextEndEvent,
    TextStartEvent,
    ToolCall,
    ToolCallEndEvent,
    ToolResultMessage,
    Usage,
    UserMessage,
)


def _claude_model() -> Model[Any]:
    return Model[Any](
        id="claude-sonnet-4-6",
        name="Claude Sonnet 4.6",
        api="anthropic-messages",
        provider="anthropic",
        base_url="https://api.anthropic.com",
        reasoning=True,
        input=["text"],
        cost=ModelCost(input=3.0, output=15.0, cache_read=0.3, cache_write=3.75),
        context_window=200_000,
        max_tokens=32_000,
    )


def test_provider_registered() -> None:
    provider = get_api_provider("anthropic-messages")
    assert provider is not None
    assert provider.api == "anthropic-messages"


def test_event_stream_queue_and_result() -> None:
    import asyncio

    async def runner() -> None:
        stream = AssistantMessageEventStream()
        msg = AssistantMessage(
            content=[TextContent(text="hi")],
            api="anthropic-messages",
            provider="anthropic",
            model="claude-sonnet-4-6",
            usage=Usage(input=5, output=2, total_tokens=7),
            stop_reason="stop",
            timestamp=0,
        )
        stream.push(StartEvent(partial=msg))
        stream.push(DoneEvent(reason="stop", message=msg))

        events = [e async for e in stream]
        assert [e.type for e in events] == ["start", "done"]

        final = await stream.result()
        assert isinstance(final, AssistantMessage)
        assert final.stop_reason == "stop"

    asyncio.run(runner())


def _fake_provider_factory(
    *,
    turn1_message: AssistantMessage,
    turn2_message: AssistantMessage,
):
    """Return a stub :func:`stream_simple` that yields two scripted turns."""

    turns = [turn1_message, turn2_message]

    def fake_stream_simple(
        model: Model[Any],
        context: Context,
        options: SimpleStreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        stream = AssistantMessageEventStream()
        message = turns.pop(0)

        async def runner() -> None:
            import asyncio as _asyncio

            stream.push(StartEvent(partial=message))
            for index, block in enumerate(message.content):
                if isinstance(block, TextContent):
                    stream.push(TextStartEvent(content_index=index, partial=message))
                    stream.push(
                        TextDeltaEvent(content_index=index, delta=block.text, partial=message)
                    )
                    stream.push(
                        TextEndEvent(content_index=index, content=block.text, partial=message)
                    )
                elif isinstance(block, ToolCall):
                    stream.push(
                        ToolCallEndEvent(
                            content_index=index, tool_call=block, partial=message
                        )
                    )
            done_reason: StopReason = message.stop_reason if message.stop_reason in ("stop", "length", "toolUse") else "stop"
            stream.push(DoneEvent(reason=done_reason, message=message))
            stream.end()
            await _asyncio.sleep(0)

        import asyncio as _asyncio

        task = _asyncio.create_task(runner())
        stream._smoke_runner = task  # type: ignore[attr-defined]
        return stream

    return fake_stream_simple


@pytest.mark.asyncio
async def test_tool_loop_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """One turn with a tool call, then a turn that finishes with ``stop``."""

    model = _claude_model()

    turn1 = AssistantMessage(
        content=[
            ToolCall(id="toolu_1", name="echo", arguments={"text": "hello"}),
        ],
        api=model.api,
        provider=model.provider,
        model=model.id,
        usage=Usage(input=10, output=2, total_tokens=12),
        stop_reason="toolUse",
        timestamp=0,
    )
    turn2 = AssistantMessage(
        content=[TextContent(text="hello")],
        api=model.api,
        provider=model.provider,
        model=model.id,
        usage=Usage(input=12, output=1, total_tokens=13),
        stop_reason="stop",
        timestamp=0,
    )

    fake_stream = _fake_provider_factory(turn1_message=turn1, turn2_message=turn2)
    monkeypatch.setattr(tool_loop, "stream_simple", fake_stream)

    async def run_tool(call: ToolCall) -> ToolResultMessage:
        return ToolResultMessage(
            tool_call_id=call.id,
            tool_name=call.name,
            content=[TextContent(text=str(call.arguments.get("text", "")))],
            is_error=False,
            timestamp=0,
        )

    context = Context(messages=[UserMessage(content="say hello", timestamp=0)])
    events = [
        event
        async for event in tool_loop.run(model, context, run_tool, options=SimpleStreamOptions(), max_turns=8)
    ]

    types = [type(e).__name__ for e in events]
    # Expected: start → toolcall_end → done (turn1), then ToolRunStart →
    # ToolRunComplete, then start → text_start/delta/end → done (turn2).
    assert "ToolRunStart" in types
    assert "ToolRunComplete" in types

    # The loop should have appended both assistant turns + one tool result.
    assert len(context.messages) == 4  # user + assistant1 + tool_result + assistant2


@pytest.mark.asyncio
async def test_tool_loop_nudges_on_tooluse_without_parseable_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``toolUse`` stop with zero ToolCall blocks must not end the loop empty.

    Observed live (session 8a0fea6a): provider reported toolUse, content had
    no parseable tool call, and the user saw an empty reply. The loop now
    appends a nudge UserMessage and runs another turn.
    """

    model = _claude_model()

    turn1 = AssistantMessage(
        content=[],
        api=model.api, provider=model.provider, model=model.id,
        usage=Usage(input=10, output=0, total_tokens=10), stop_reason="toolUse", timestamp=0,
    )
    turn2 = AssistantMessage(
        content=[TextContent(text="direct answer")],
        api=model.api, provider=model.provider, model=model.id,
        usage=Usage(input=12, output=2, total_tokens=14), stop_reason="stop", timestamp=0,
    )

    monkeypatch.setattr(
        tool_loop, "stream_simple", _fake_provider_factory(turn1_message=turn1, turn2_message=turn2)
    )

    async def run_tool(call: ToolCall) -> ToolResultMessage:  # pragma: no cover - not reached
        raise AssertionError("no tool should execute")

    context = Context(messages=[UserMessage(content="hi", timestamp=0)])
    [event async for event in tool_loop.run(model, context, run_tool, options=SimpleStreamOptions(), max_turns=8)]

    # user + empty assistant1 + nudge UserMessage + assistant2
    assert len(context.messages) == 4
    nudge = context.messages[2]
    assert isinstance(nudge, UserMessage)
    assert "no parseable tool call" in str(nudge.content)
    final = context.messages[3]
    assert isinstance(final, AssistantMessage)
    assert final.stop_reason == "stop"


@pytest.mark.asyncio
async def test_tool_loop_forces_final_answer_when_cap_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cap exhaustion mid-tool-use must end with an answer, not narration.

    Observed live: the loop hit max_turns while the model still wanted
    tools, so the caller's final message was tool-call narration (or empty)
    and the user saw a blank reply. The loop now appends a budget-exhausted
    UserMessage and runs one final answer turn.
    """

    model = _claude_model()

    turn1 = AssistantMessage(
        content=[ToolCall(id="toolu_cap", name="echo", arguments={"text": "hi"})],
        api=model.api, provider=model.provider, model=model.id,
        usage=Usage(input=10, output=2, total_tokens=12), stop_reason="toolUse", timestamp=0,
    )
    turn2 = AssistantMessage(
        content=[TextContent(text="answer from collected results")],
        api=model.api, provider=model.provider, model=model.id,
        usage=Usage(input=14, output=3, total_tokens=17), stop_reason="stop", timestamp=0,
    )

    monkeypatch.setattr(
        tool_loop, "stream_simple", _fake_provider_factory(turn1_message=turn1, turn2_message=turn2)
    )

    executed: list[str] = []

    async def run_tool(call: ToolCall) -> ToolResultMessage:
        executed.append(call.name)
        return ToolResultMessage(
            tool_call_id=call.id,
            tool_name=call.name,
            content=[TextContent(text="result")],
            is_error=False,
            timestamp=0,
        )

    context = Context(messages=[UserMessage(content="net worth?", timestamp=0)])
    [event async for event in tool_loop.run(model, context, run_tool, options=SimpleStreamOptions(), max_turns=1)]

    assert executed == ["echo"]
    # user + assistant1 + tool_result + budget UserMessage + final assistant
    assert len(context.messages) == 5
    nudge = context.messages[3]
    assert isinstance(nudge, UserMessage)
    assert "Tool budget exhausted" in str(nudge.content)
    final = context.messages[4]
    assert isinstance(final, AssistantMessage)
    assert final.stop_reason == "stop"
    final_text = final.content[0]
    assert isinstance(final_text, TextContent)
    assert "answer from collected results" in final_text.text


async def _big_json_tool_result(call: ToolCall) -> ToolResultMessage:
    payload = json.dumps(
        [{"id": i, "name": f"row_{i}", "email": f"row_{i}@ex.com", "role": "member"} for i in range(120)]
    )
    return ToolResultMessage(
        tool_call_id=call.id,
        tool_name=call.name,
        content=[TextContent(text=payload)],
        is_error=False,
        timestamp=0,
    )


def _two_turn_tool_loop() -> tuple[Model[Any], AssistantMessage, AssistantMessage]:
    model = _claude_model()
    turn1 = AssistantMessage(
        content=[ToolCall(id="toolu_1", name="list_rows", arguments={})],
        api=model.api, provider=model.provider, model=model.id,
        usage=Usage(input=10, output=2, total_tokens=12), stop_reason="toolUse", timestamp=0,
    )
    turn2 = AssistantMessage(
        content=[TextContent(text="done")],
        api=model.api, provider=model.provider, model=model.id,
        usage=Usage(input=12, output=1, total_tokens=13), stop_reason="stop", timestamp=0,
    )
    return model, turn1, turn2


@pytest.mark.asyncio
async def test_tool_loop_compresses_results_when_flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flag ON: the accumulated tool result is compressed before the next turn and
    stats land in the sink (proves the Phase 2/3 threading end-to-end)."""
    model, turn1, turn2 = _two_turn_tool_loop()
    monkeypatch.setattr(tool_loop, "stream_simple", _fake_provider_factory(turn1_message=turn1, turn2_message=turn2))

    context = Context(messages=[UserMessage(content="list", timestamp=0)])
    sink: dict[str, int] = {}
    async for _ in tool_loop.run(
        model, context, _big_json_tool_result, options=SimpleStreamOptions(), max_turns=8,
        compress_tool_results_enabled=True, compression_stats_sink=sink,
    ):
        pass

    block = next(m for m in context.messages if isinstance(m, ToolResultMessage)).content[0]
    assert isinstance(block, TextContent)
    assert block.text.lstrip().startswith('"[')  # SmartCrusher tabular header
    assert sink["blocks_compressed"] == 1
    assert sink["tokens_after"] < sink["tokens_before"]


@pytest.mark.asyncio
async def test_tool_loop_leaves_results_raw_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flag OFF (default): the tool result passes through untouched, sink stays empty."""
    model, turn1, turn2 = _two_turn_tool_loop()
    monkeypatch.setattr(tool_loop, "stream_simple", _fake_provider_factory(turn1_message=turn1, turn2_message=turn2))

    context = Context(messages=[UserMessage(content="list", timestamp=0)])
    sink: dict[str, int] = {}
    async for _ in tool_loop.run(
        model, context, _big_json_tool_result, options=SimpleStreamOptions(), max_turns=8,
        compress_tool_results_enabled=False, compression_stats_sink=sink,
    ):
        pass

    block = next(m for m in context.messages if isinstance(m, ToolResultMessage)).content[0]
    assert isinstance(block, TextContent)
    assert block.text.lstrip().startswith("[{")  # still raw JSON
    assert sink == {}


@pytest.mark.asyncio
async def test_sse_writer_emits_contract_events() -> None:
    """SSE writer surfaces the 9-event downstream contract correctly."""

    model = _claude_model()
    msg_tool = AssistantMessage(
        content=[ToolCall(id="toolu_1", name="echo", arguments={"text": "x"})],
        api=model.api,
        provider=model.provider,
        model=model.id,
        usage=Usage(input=10, output=2, total_tokens=12),
        stop_reason="toolUse",
        timestamp=0,
    )
    msg_done = AssistantMessage(
        content=[TextContent(text="hi")],
        api=model.api,
        provider=model.provider,
        model=model.id,
        usage=Usage(input=12, output=1, total_tokens=13),
        stop_reason="stop",
        timestamp=0,
    )

    tool_block = msg_tool.content[0]
    assert isinstance(tool_block, ToolCall)

    async def stream_events():
        yield TextDeltaEvent(content_index=0, delta="hi", partial=msg_done)
        yield ToolCallEndEvent(content_index=0, tool_call=tool_block, partial=msg_tool)
        yield tool_loop.ToolRunStart(tool_call=tool_block)
        yield tool_loop.ToolRunComplete(
            tool_call=tool_block,
            result=ToolResultMessage(
                tool_call_id="toolu_1",
                tool_name="echo",
                content=[TextContent(text="x")],
                is_error=False,
                timestamp=0,
            ),
        )
        yield DoneEvent(reason="stop", message=msg_done)

    writer = SseWriter(session_id="sess-1")
    chunks: list[dict[str, Any]] = []
    async for raw in write_events(stream_events(), writer):
        assert raw.startswith("data: ")
        assert raw.endswith("\n\n")
        chunks.append(json.loads(raw[len("data: ") : -2]))

    types = [c["type"] for c in chunks]
    assert types == ["content", "tool_use", "tool_start", "tool_result", "done"]
    assert chunks[0]["content"] == "hi"
    assert chunks[1]["tool_id"] == "toolu_1"
    assert chunks[1]["tool_name"] == "echo"
    assert chunks[2]["tool_id"] == "toolu_1"
    assert chunks[3]["tool_status"] == "complete"
    assert chunks[3]["tool_result"] == "x"
    assert chunks[4]["finish_reason"] == "stop"
    assert chunks[4]["session_id"] == "sess-1"
    # seq is monotonic.
    seqs = [c["seq"] for c in chunks]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
