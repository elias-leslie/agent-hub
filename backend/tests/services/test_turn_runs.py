"""Server-owned chat turns: they outlive the client, replay by seq, and end visibly when interrupted."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator

import pytest

from app.api.complete import stream_completion
from app.api.complete.streaming_context import StreamContext
from app.llm.types import TextDeltaEvent
from app.services import turn_runs
from app.services.llm_messages import Message
from app.services.turn_runs import (
    DONE_CHUNK,
    HEARTBEAT_CHUNK,
    TurnLogGap,
    TurnRegistry,
    TurnRunning,
    turn_state_for,
)
from tests.api.stream_test_support import patched_done_persistence
from tests.api.test_complete_streaming import _done_event, _partial_message
from tests.model_ids import CLAUDE_SONNET


def event(seq: int, kind: str, **fields: object) -> str:
    return f"data: {json.dumps({'type': kind, 'seq': seq, **fields})}\n\n"


def seqs(chunks: list[str]) -> list[int]:
    return [json.loads(c[6:])["seq"] for c in chunks if c.startswith("data: {")]


def types(chunks: list[str]) -> list[str]:
    return [json.loads(c[6:])["type"] for c in chunks if c.startswith("data: {")]


async def gated(head: list[str], gate: asyncio.Event, tail: list[str]) -> AsyncIterator[str]:
    """A turn that emits ``head``, waits for ``gate``, then emits ``tail`` and ends."""
    for chunk in head:
        yield chunk
    await gate.wait()
    for chunk in tail:
        yield chunk
    yield DONE_CHUNK


async def drain(subscription: AsyncIterator[str]) -> list[str]:
    return [chunk async for chunk in subscription]


async def read(subscription: AsyncGenerator[str], count: int) -> list[str]:
    out: list[str] = []
    async for chunk in subscription:
        out.append(chunk)
        if len(out) == count:
            break
    return out


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> TurnRegistry:
    fresh = TurnRegistry()
    monkeypatch.setattr(turn_runs, "registry", fresh)  # what StreamContext.cancel and turn_state_for consult
    return fresh


HEAD = [event(1, "connected", session_id="s"), event(2, "content", content="a"), event(3, "content", content="b")]
TAIL = [event(4, "content", content="c"), event(5, "done", session_id="s")]


async def test_disconnect_mid_turn_leaves_the_turn_finishing(registry: TurnRegistry) -> None:
    gate = asyncio.Event()
    run = registry.start("s", gated(HEAD, gate, TAIL), persist=False)
    first = run.follow()
    assert seqs(await read(first, 3)) == [1, 2, 3]
    await first.aclose()  # the client goes away mid-turn

    assert run.running and turn_state_for_run(registry, "s") == "running"
    gate.set()
    await asyncio.wait_for(run.finished.wait(), 2)

    assert run.state == "completed"
    assert seqs(await drain(run.follow())) == [1, 2, 3, 4, 5]


async def test_reattach_gets_exactly_the_events_after_seq(registry: TurnRegistry) -> None:
    gate = asyncio.Event()
    run = registry.start("s", gated(HEAD, gate, TAIL), persist=False)
    await read(run.follow(), 2)
    late = asyncio.create_task(drain(run.follow(after_seq=2)))
    await asyncio.sleep(0)
    gate.set()
    chunks = await asyncio.wait_for(late, 2)

    assert seqs(chunks) == [3, 4, 5]  # nothing before 3, nothing twice
    assert types(chunks) == ["content", "content", "done"]
    assert chunks[-1] == DONE_CHUNK
    assert seqs(await drain(run.follow(after_seq=5))) == []  # caught up on a finished turn: just the end marker


async def test_two_subscribers_see_the_same_stream(registry: TurnRegistry) -> None:
    gate = asyncio.Event()
    run = registry.start("s", gated(HEAD, gate, TAIL), persist=False)
    first = asyncio.create_task(drain(run.follow()))
    await asyncio.sleep(0)
    second = asyncio.create_task(drain(run.follow()))
    await asyncio.sleep(0)
    gate.set()
    a, b = await asyncio.wait_for(asyncio.gather(first, second), 2)
    assert a == b == [*HEAD, *TAIL, DONE_CHUNK]


async def test_a_subscriber_that_is_idle_gets_heartbeats(registry: TurnRegistry) -> None:
    gate = asyncio.Event()
    run = registry.start("s", gated(HEAD, gate, TAIL), persist=False)
    chunks = await read(run.follow(heartbeat_seconds=0.01), 4)
    assert chunks[:3] == HEAD and chunks[3] == HEARTBEAT_CHUNK
    gate.set()
    await asyncio.wait_for(run.finished.wait(), 2)


async def test_cancel_from_a_second_client_reaches_every_subscriber(registry: TurnRegistry) -> None:
    gate = asyncio.Event()

    async def provider(*_args: object, **_kwargs: object):
        yield TextDeltaEvent(content_index=0, delta="Hello", partial=_partial_message())
        await gate.wait()
        yield TextDeltaEvent(content_index=0, delta=" world", partial=_partial_message())
        yield _done_event()

    with patched_done_persistence(), pytest.MonkeyPatch.context() as patch:
        patch.setattr("app.api.complete.streaming.run_completion_stream", provider)
        stream = stream_completion(
            messages=[Message(role="user", content="hi")],
            model=CLAUDE_SONNET,
            provider="claude",
            temperature=0.7,
            session_id="cancel-me",
            turn_id="t1",
        )
        run = registry.start("cancel-me", stream, turn_id="t1", persist=False)
        original = asyncio.create_task(drain(run.follow()))
        attached = asyncio.create_task(drain(run.follow()))
        for _ in range(50):
            if "Hello" in "".join(c.chunk for c in run.events_after(0)):
                break
            await asyncio.sleep(0.01)

        assert StreamContext.cancel("cancel-me") is True  # what POST /complete/cancel calls, from any client
        assert run.cancel_requested
        gate.set()
        a, b = await asyncio.wait_for(asyncio.gather(original, attached), 2)

    assert a == b
    assert types(a)[0] == "connected" and json.loads(a[0][6:])["turn_id"] == "t1"
    assert types(a)[-1] == "cancel_acknowledged"
    assert "done" not in types(a)
    assert run.state == "cancelled"


async def test_interrupted_turn_ends_with_an_error_event_for_every_subscriber(registry: TurnRegistry) -> None:
    gate = asyncio.Event()
    run = registry.start("s", gated(HEAD, gate, TAIL), persist=False)
    watcher = asyncio.create_task(drain(run.follow()))
    await asyncio.sleep(0.01)

    await registry.shutdown()  # the backend is stopping mid-turn
    chunks = await asyncio.wait_for(watcher, 2)

    assert run.state == "interrupted" and run.finished.is_set()
    last = json.loads(chunks[-2][6:])
    assert last["type"] == "error" and last["code"] == "turn_interrupted" and last["seq"] == 4
    assert chunks[-1] == DONE_CHUNK
    assert seqs(await drain(run.follow(after_seq=3))) == [4]  # a later reattach still learns how it ended


async def test_a_turn_that_ends_without_a_result_says_so(registry: TurnRegistry) -> None:
    async def silent() -> AsyncIterator[str]:
        yield event(1, "connected", session_id="s")
        yield DONE_CHUNK

    run = registry.start("s", silent(), persist=False)
    chunks = await asyncio.wait_for(drain(run.follow()), 2)
    assert types(chunks) == ["connected", "error"] and run.state == "error"


async def test_one_turn_runs_per_session_and_a_finished_one_can_be_replaced(registry: TurnRegistry) -> None:
    gate = asyncio.Event()
    run = registry.start("s", gated(HEAD, gate, TAIL), persist=False)
    with pytest.raises(TurnRunning):
        registry.start("s", gated(HEAD, gate, TAIL), persist=False)
    gate.set()
    await asyncio.wait_for(run.finished.wait(), 2)

    second = registry.start("s", gated([], gate, [event(1, "done", session_id="s")]), persist=False)
    await asyncio.wait_for(second.finished.wait(), 2)
    assert registry.get("s") is second


async def test_log_is_capped_and_a_replay_from_before_it_is_refused(
    registry: TurnRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(turn_runs.settings, "turn_log_max_bytes", 1_000_000)
    big = "x" * 400_000
    chunks = [event(n, "content", content=big) for n in range(1, 6)] + [event(6, "done", session_id="s")]
    run = registry.start("s", _emit(chunks), persist=False)
    await asyncio.wait_for(run.finished.wait(), 2)

    kept = [e.seq for e in run.events_after(run.last_seq - 3)]
    assert kept[-1] == 6
    with pytest.raises(TurnLogGap):
        run.events_after(0)


async def _emit(chunks: list[str]) -> AsyncIterator[str]:
    for chunk in chunks:
        yield chunk
    yield DONE_CHUNK


async def test_finished_turns_are_kept_for_the_newest_sessions_only(
    registry: TurnRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(turn_runs.settings, "turn_log_retained_finished", 2)
    for name in ("a", "b", "c"):
        run = registry.start(name, _emit([event(1, "done", session_id=name)]), persist=False)
        await asyncio.wait_for(run.finished.wait(), 2)
        await asyncio.sleep(0)
    assert registry.get("a") is None and registry.get("b") is not None and registry.get("c") is not None


async def test_session_info_shows_the_running_phase(registry: TurnRegistry) -> None:
    fresh = registry
    gate = asyncio.Event()
    head = [event(1, "connected", session_id="s"), event(2, "tool_start", tool_id="t", tool_name="read_file")]
    run = fresh.start("s", gated(head, gate, [event(3, "done", session_id="s")]), persist=False)
    await read(run.follow(), 2)

    assert turn_state_for("s") == ("running", "running_tool:read_file")
    assert turn_state_for("other") == ("idle", None)
    gate.set()
    await asyncio.wait_for(run.finished.wait(), 2)
    assert turn_state_for("s") == ("idle", None)


def turn_state_for_run(registry: TurnRegistry, session_id: str) -> str:
    return "running" if registry.running(session_id) else "idle"
