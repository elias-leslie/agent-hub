"""Reattach endpoint, persisted turn state and the restart sweep, against a rolled-back test database."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SessionEvent
from app.services import turn_runs
from app.services.turn_runs import DONE_CHUNK, TURN_KEY, TurnRegistry, interrupt_orphaned_turns
from tests.api.test_sessions_listing_pg import add_session, api, pg_db  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration


def event(seq: int, kind: str, **fields: object) -> str:
    return f"data: {json.dumps({'type': kind, 'seq': seq, **fields})}\n\n"


def parse(body: str) -> list[dict[str, Any]]:
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: {")]


async def gated(head: list[str], gate: asyncio.Event, tail: list[str]) -> AsyncIterator[str]:
    for chunk in head:
        yield chunk
    await gate.wait()
    for chunk in tail:
        yield chunk
    yield DONE_CHUNK


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[TurnRegistry]:
    fresh = TurnRegistry()
    monkeypatch.setattr(turn_runs, "registry", fresh)
    monkeypatch.setattr("app.api.session_stream.registry", fresh)
    yield fresh


@pytest.fixture
def test_session_factory(pg_db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """Background turn bookkeeping opens its own sessions; point them at the test transaction."""

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield pg_db

    monkeypatch.setattr("app.db.async_session", factory)


async def persisted_turn(db: AsyncSession, session_id: str) -> dict[str, Any]:
    from app.models import Session

    row = (await db.execute(select(Session).where(Session.id == session_id))).scalar_one()
    await db.refresh(row)
    return (row.provider_metadata or {}).get(TURN_KEY, {})


async def test_unknown_session_is_404(api: httpx.AsyncClient) -> None:  # noqa: F811
    assert (await api.get("/api/sessions/nope/stream")).status_code == 404


async def test_attach_replays_after_seq_then_follows_the_running_turn(
    api: httpx.AsyncClient, pg_db: AsyncSession, registry: TurnRegistry, test_session_factory: None  # noqa: F811
) -> None:
    await add_session(pg_db, "chat-1", minutes=1, session_type="chat", status="active")
    gate = asyncio.Event()
    head = [event(1, "connected", session_id="chat-1"), event(2, "content", content="a")]
    run = registry.start("chat-1", gated(head, gate, [event(3, "content", content="b"), event(4, "done")]))
    await asyncio.sleep(0.05)

    info = (await api.get("/api/sessions/chat-1", params={"include_events": "false"})).json()
    assert (info["turn_state"], info["turn_phase"]) == ("running", "responding")
    assert (await persisted_turn(pg_db, "chat-1"))["state"] == "running"

    attach = asyncio.create_task(api.get("/api/sessions/chat-1/stream", params={"after_seq": 1}))
    await asyncio.sleep(0.05)
    gate.set()
    response = await asyncio.wait_for(attach, 5)

    assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
    assert [e["seq"] for e in parse(response.text)] == [2, 3, 4]
    assert response.text.endswith("data: [DONE]\n\n")
    await asyncio.wait_for(run.finished.wait(), 2)
    done = await persisted_turn(pg_db, "chat-1")
    assert (done["state"], done["last_seq"]) == ("completed", 4)
    info = (await api.get("/api/sessions/chat-1", params={"include_events": "false"})).json()
    assert (info["turn_state"], info["turn_phase"]) == ("idle", None)


async def test_attach_refuses_a_wrong_turn_and_a_dropped_replay_point(
    api: httpx.AsyncClient, pg_db: AsyncSession, registry: TurnRegistry, test_session_factory: None  # noqa: F811
) -> None:
    await add_session(pg_db, "chat-2", minutes=1, session_type="chat", status="active")
    gate = asyncio.Event()
    run = registry.start("chat-2", gated([event(1, "connected", session_id="chat-2")], gate, []), turn_id="t-1")
    await asyncio.sleep(0.05)

    mismatch = await api.get("/api/sessions/chat-2/stream", params={"turn_id": "other"})
    assert mismatch.status_code == 409 and mismatch.json()["error"] == "turn_mismatch"

    run._oldest_kept = 10  # events 1..9 were dropped under the size cap
    gap = await api.get("/api/sessions/chat-2/stream", params={"after_seq": 2})
    assert gap.status_code == 410 and gap.json()["error"] == "turn_log_gap" and gap.json()["details"]["oldest_seq"] == 10
    run._oldest_kept = 1
    gate.set()
    await asyncio.wait_for(run.finished.wait(), 2)


async def test_with_no_turn_in_memory_attach_states_how_the_last_one_ended(
    api: httpx.AsyncClient, pg_db: AsyncSession, registry: TurnRegistry  # noqa: F811
) -> None:
    await add_session(pg_db, "idle-1", minutes=1, session_type="chat")
    fresh = parse((await api.get("/api/sessions/idle-1/stream")).text)
    assert fresh == [{"type": "idle", "session_id": "idle-1", "last_state": "none", "turn_id": None, "ended_at": None}]

    await add_session(pg_db, "idle-2", minutes=2, session_type="chat",
                      metadata={TURN_KEY: {"state": "completed", "turn_id": "t", "ended_at": "2026-10-28T00:00:00+00:00"}})
    ended = parse((await api.get("/api/sessions/idle-2/stream")).text)
    assert [(e["type"], e["last_state"]) for e in ended] == [("idle", "completed")]


async def test_restart_sweep_ends_a_running_turn_as_interrupted_and_reattach_says_so(
    api: httpx.AsyncClient, pg_db: AsyncSession, registry: TurnRegistry, test_session_factory: None  # noqa: F811
) -> None:
    await add_session(pg_db, "orphan", minutes=1, session_type="chat", status="active",
                      metadata={TURN_KEY: {"state": "running", "turn_id": "gone", "started_at": "2026-10-28T00:00:00+00:00"}})
    await add_session(pg_db, "fine", minutes=2, session_type="chat",
                      metadata={TURN_KEY: {"state": "completed", "turn_id": "ok"}})

    assert await interrupt_orphaned_turns() == 1

    assert (await persisted_turn(pg_db, "orphan"))["state"] == "interrupted"
    assert (await persisted_turn(pg_db, "fine"))["state"] == "completed"
    errors = (await pg_db.execute(select(SessionEvent).where(SessionEvent.session_id == "orphan"))).scalars().all()
    assert [e.event_type for e in errors] == ["error"] and "interrupted" in (errors[0].content or "")
    detail = (await api.get("/api/sessions/orphan", params={"include_events": "false"})).json()
    assert "interrupted" in detail["live_activity"]["summary"] and detail["turn_state"] == "idle"

    events = parse((await api.get("/api/sessions/orphan/stream", params={"after_seq": 7})).text)
    assert [(e["type"], e["seq"], e["code"]) for e in events] == [("error", 8, "turn_interrupted")]


async def test_shutdown_persists_the_interruption(
    pg_db: AsyncSession, registry: TurnRegistry, test_session_factory: None  # noqa: F811
) -> None:
    await add_session(pg_db, "live", minutes=1, session_type="chat", status="active")
    run = registry.start("live", gated([event(1, "connected", session_id="live")], asyncio.Event(), []))
    await asyncio.sleep(0.05)

    await registry.shutdown()

    assert run.state == "interrupted"
    stored = await persisted_turn(pg_db, "live")
    assert stored["state"] == "interrupted" and stored["last_seq"] == 2


def _assistant(**fields: Any) -> Any:
    import time

    from app.llm.types import AssistantMessage, Usage
    from tests.model_ids import CLAUDE_SONNET

    return AssistantMessage(
        content=[], api="anthropic-messages", provider="claude", model=CLAUDE_SONNET,
        usage=Usage(input=5, output=2), stop_reason="stop", timestamp=int(time.time() * 1000), **fields,
    )


async def test_the_prompt_is_stored_at_turn_start_so_a_second_client_sees_it_mid_turn(
    api: httpx.AsyncClient, pg_db: AsyncSession, registry: TurnRegistry, test_session_factory: None  # noqa: F811
) -> None:
    from unittest.mock import patch

    from app.api.complete import stream_completion
    from app.api.complete.schemas import MessageInput
    from app.llm.types import DoneEvent, TextDeltaEvent
    from app.services.llm_messages import Message
    from tests.api.stream_test_support import patched_done_persistence
    from tests.model_ids import CLAUDE_SONNET

    await add_session(pg_db, "prompted", minutes=1, session_type="chat", status="active")
    gate = asyncio.Event()
    prompt = "Please audit the cache layer"

    async def provider_stream(*_args: object, **_kwargs: object) -> AsyncIterator[Any]:
        yield TextDeltaEvent(content_index=0, delta="Working on it. ", partial=_assistant())
        await gate.wait()
        yield DoneEvent(reason="stop", message=_assistant())

    with (
        patched_done_persistence() as persistence,
        patch("app.api.complete.streaming.run_completion_stream", new=provider_stream),
    ):
        stream = stream_completion(
            messages=[Message(role="user", content=prompt)],
            model=CLAUDE_SONNET,
            provider="claude",
            temperature=0.7,
            session_id="prompted",
            db=pg_db,
            user_messages=[MessageInput(role="user", content=prompt)],
        )
        run = registry.start("prompted", stream)
        await asyncio.sleep(0.2)

        # A second client opens the session while the first client's turn is still running.
        mid = (await api.get("/api/sessions/prompted", params={"include_events": "true"})).json()
        assert mid["turn_state"] == "running"
        assert [(m["role"], m["content"]) for m in mid["messages"]] == [("user", prompt)]
        attach = asyncio.create_task(api.get("/api/sessions/prompted/stream"))
        await asyncio.sleep(0.05)
        gate.set()
        response = await asyncio.wait_for(attach, 5)
        await asyncio.wait_for(run.finished.wait(), 2)

    assert [e["type"] for e in parse(response.text)][-1] == "done"
    # The end-of-turn save no longer stores the prompt a second time; it names it so it gets the turn's tokens.
    done_save = persistence.save_messages_to_db.await_args.kwargs
    assert not done_save["user_messages"]
    assert done_save["prompt_event_id"] == mid["messages"][0]["id"]


async def test_a_prompt_stored_at_turn_start_gets_the_turns_input_tokens_when_it_ends(
    pg_db: AsyncSession, test_session_factory: None  # noqa: F811
) -> None:
    import time

    from sqlalchemy import select

    from app.api.complete.schemas import MessageInput
    from app.api.complete.streaming_persistence import save_messages_to_db, save_turn_prompt_to_db
    from app.models import SessionEvent, SessionEventType
    from tests.model_ids import CLAUDE_SONNET

    await add_session(pg_db, "counted", minutes=1, session_type="chat", status="active")
    event_id = await save_turn_prompt_to_db("counted", [MessageInput(role="user", content="Count these tokens")])
    assert event_id is not None

    await save_messages_to_db(
        session_id="counted", user_messages=[], accumulated_content="Done.", input_tokens=6254,
        output_tokens=12, model=CLAUDE_SONNET, agent_used=None, stream_start=time.monotonic(),
        prompt_event_id=event_id,
    )

    rows = (
        await pg_db.execute(
            select(SessionEvent.event_type, SessionEvent.tokens)
            .where(SessionEvent.session_id == "counted")
            .order_by(SessionEvent.sequence)
        )
    ).all()
    pg_db.expire_all()
    assert [(row.event_type, row.tokens) for row in rows] == [
        (SessionEventType.USER_MESSAGE, 6254),
        (SessionEventType.ASSISTANT_MESSAGE, 12),
    ]
