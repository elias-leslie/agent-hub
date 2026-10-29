"""Stop ends a streamed turn at once: no content after the cancel event, and the provider request is closed."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.complete import stream_completion
from app.api.complete.schemas import MessageInput
from app.api.complete.streaming_context import StreamContext
from app.llm.types import DoneEvent, TextDeltaEvent, ThinkingDeltaEvent
from app.services.llm_messages import Message
from app.services.turn_runs import TurnRegistry
from tests.api.stream_test_support import patched_done_persistence
from tests.api.test_session_stream_pg import (  # noqa: F401  (fixtures)
    _assistant,
    parse,
    registry,
    test_session_factory,
)
from tests.api.test_sessions_listing_pg import add_session, api, pg_db  # noqa: F401  (fixtures)
from tests.model_ids import CLAUDE_SONNET

pytestmark = pytest.mark.integration


class ProviderProbe:
    """What the fake provider saw: how many deltas it produced and whether its generator was finalized."""

    def __init__(self) -> None:
        self.produced = 0
        self.closed = asyncio.Event()


def _turn(session_id: str, db: AsyncSession, provider: Any) -> Any:
    patches = (
        patched_done_persistence(),
        patch("app.api.complete.streaming.run_completion_stream", new=provider),
    )
    return patches, stream_completion(
        messages=[Message(role="user", content="go")],
        model=CLAUDE_SONNET,
        provider="claude",
        temperature=0.7,
        session_id=session_id,
        db=db,
        user_messages=[MessageInput(role="user", content="go")],
    )


async def test_stop_while_text_streams_publishes_nothing_after_the_cancel_and_closes_the_provider(
    pg_db: AsyncSession, registry: TurnRegistry, test_session_factory: None  # noqa: F811
) -> None:
    await add_session(pg_db, "stop-text", minutes=1, session_type="chat", status="active")
    probe = ProviderProbe()

    async def provider_stream(*_a: object, **_k: object) -> AsyncIterator[Any]:
        try:
            while True:  # a fast model: every delta is ready the moment it is asked for
                probe.produced += 1
                yield TextDeltaEvent(content_index=0, delta=f"word{probe.produced} ", partial=_assistant())
                await asyncio.sleep(0)
        finally:
            probe.closed.set()

    patches, stream = _turn("stop-text", pg_db, provider_stream)
    with patches[0], patches[1]:
        run = registry.start("stop-text", stream)
        while probe.produced < 40:  # well past the heartbeat queue's depth: chunks are buffered when Stop lands
            await asyncio.sleep(0.005)
        assert StreamContext.cancel("stop-text") is True
        await asyncio.wait_for(run.finished.wait(), 2)
        seen_at_stop = probe.produced
        await asyncio.sleep(0.1)

    events = parse("".join(e.chunk for e in run.events_after(0)))
    kinds = [e["type"] for e in events]
    assert kinds[-1] == "cancel_acknowledged" and kinds.count("cancel_acknowledged") == 1
    assert run.state == "cancelled"
    assert probe.closed.is_set(), "the provider iterator was left open"
    assert probe.produced == seen_at_stop, "the provider kept producing after the cancel"


async def test_stop_while_the_model_is_silent_does_not_wait_for_its_next_chunk(
    pg_db: AsyncSession, registry: TurnRegistry, test_session_factory: None  # noqa: F811
) -> None:
    await add_session(pg_db, "stop-silent", minutes=1, session_type="chat", status="active")
    probe = ProviderProbe()
    never = asyncio.Event()

    async def provider_stream(*_a: object, **_k: object) -> AsyncIterator[Any]:
        try:
            yield ThinkingDeltaEvent(content_index=0, delta="hmm", partial=_assistant())
            await never.wait()  # no further chunk, ever
            yield DoneEvent(reason="stop", message=_assistant())
        finally:
            probe.closed.set()

    patches, stream = _turn("stop-silent", pg_db, provider_stream)
    with patches[0], patches[1]:
        run = registry.start("stop-silent", stream)
        await asyncio.sleep(0.1)
        started = time.monotonic()
        assert StreamContext.cancel("stop-silent") is True
        await asyncio.wait_for(run.finished.wait(), 2)
        assert time.monotonic() - started < 1.0

    assert [e["type"] for e in parse("".join(e.chunk for e in run.events_after(0)))][-1] == "cancel_acknowledged"
    assert probe.closed.is_set()
    assert registry.running("stop-silent") is None


async def test_a_late_chunk_after_the_terminal_event_is_never_published(
    registry: TurnRegistry,  # noqa: F811
) -> None:
    from tests.api.test_session_stream_pg import event

    async def source() -> AsyncIterator[str]:
        yield event(1, "content", content="a")
        yield event(2, "cancel_acknowledged")
        yield event(3, "content", content="late")
        yield "data: [DONE]\n\n"

    run = registry.start("late", source(), persist=False)
    await asyncio.wait_for(run.finished.wait(), 2)
    assert [e.type for e in run.events_after(0)] == ["content", "cancel_acknowledged"]
    assert run.state == "cancelled"


async def test_cancel_endpoint_stops_a_turn_and_subscribers_see_nothing_after_it(
    api: httpx.AsyncClient, pg_db: AsyncSession, registry: TurnRegistry, test_session_factory: None  # noqa: F811
) -> None:
    await add_session(pg_db, "stop-api", minutes=1, session_type="chat", status="active")
    probe = ProviderProbe()

    async def provider_stream(*_a: object, **_k: object) -> AsyncIterator[Any]:
        try:
            while True:
                probe.produced += 1
                yield TextDeltaEvent(content_index=0, delta="x", partial=_assistant())
                await asyncio.sleep(0)
        finally:
            probe.closed.set()

    patches, stream = _turn("stop-api", pg_db, provider_stream)
    with patches[0], patches[1]:
        run = registry.start("stop-api", stream)
        attach = asyncio.create_task(api.get("/api/sessions/stop-api/stream"))
        await asyncio.sleep(0.1)
        cancelled = (await api.post("/api/complete/cancel", json={"session_id": "stop-api"})).json()
        response = await asyncio.wait_for(attach, 5)
        await asyncio.wait_for(run.finished.wait(), 2)

    assert cancelled["cancelled"] is True
    kinds = [e["type"] for e in parse(response.text)]
    assert kinds[-1] == "cancel_acknowledged" and "content" in kinds[:-1]
    assert probe.closed.is_set()


async def test_the_turn_phase_is_thinking_only_while_reasoning_streams(
    pg_db: AsyncSession, registry: TurnRegistry, test_session_factory: None  # noqa: F811
) -> None:
    await add_session(pg_db, "phase", minutes=1, session_type="chat", status="active")
    gates = [asyncio.Event(), asyncio.Event(), asyncio.Event()]

    async def provider_stream(*_a: object, **_k: object) -> AsyncIterator[Any]:
        yield ThinkingDeltaEvent(content_index=0, delta="hm", partial=_assistant())
        await gates[0].wait()
        yield TextDeltaEvent(content_index=1, delta="The answer", partial=_assistant())
        await gates[1].wait()
        yield DoneEvent(reason="stop", message=_assistant())

    patches, stream = _turn("phase", pg_db, provider_stream)
    with patches[0], patches[1]:
        run = registry.start("phase", stream)
        await asyncio.sleep(0.1)
        assert run.phase == "thinking"
        gates[0].set()
        await asyncio.sleep(0.1)
        assert run.phase == "responding"  # text is streaming: no longer "thinking"
        gates[1].set()
        await asyncio.wait_for(run.finished.wait(), 2)
    assert run.phase == "idle"
