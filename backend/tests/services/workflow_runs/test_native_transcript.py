"""Pi, Codex and Claude Code attempts get their native transcript as session events on the attempt session."""

from __future__ import annotations

import json
import os
import shutil
from collections import Counter
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import Enum, func, make_url, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import CreateTable

from app.models import CostLog, Session, SessionEvent
from app.services.workflow_runs.native_transcript import ingest_attempt_transcript

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "workflow_executors"
PI_ID = "01a18394-8e96-764c-bce0-621d4806e5e3"
CODEX_ID = "01a187d7-35da-7ea1-9c27-5bdaf4a247cc"
CLAUDE_ID = "d90d5e2f-a941-4bd1-a596-f7e03aa71194"

# executor: fixture file (a trimmed, sanitized real transcript) and the native session id in it
CASES = {
    "pi": ("native_pi_attempt.jsonl", PI_ID),
    "codex": ("native_codex_attempt.jsonl", CODEX_ID),
    "claude_code": ("native_claude_code_attempt.jsonl", CLAUDE_ID),
}


@pytest_asyncio.fixture
async def pg_db() -> AsyncGenerator[AsyncSession]:
    configured = os.environ.get("TEST_AGENT_HUB_DB_URL")
    if not configured:
        pytest.skip("TEST_AGENT_HUB_DB_URL is required")
    url = make_url(configured).set(drivername="postgresql+asyncpg")
    assert url.database and url.database.endswith("_test")
    engine = create_async_engine(url)
    schema = f"native_transcript_{uuid4().hex}"
    async with engine.connect() as connection:
        transaction = await connection.begin()
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
        await connection.execute(text(f"SET LOCAL search_path TO {schema}"))

        def create_tables(sync_connection: object) -> None:
            for table in (Session.__table__, SessionEvent.__table__, CostLog.__table__):
                for column in table.columns:
                    if isinstance(column.type, Enum):
                        column.type.create(sync_connection, checkfirst=True)
                sync_connection.execute(CreateTable(table, include_foreign_key_constraints=[]))  # type: ignore[attr-defined]

        await connection.run_sync(create_tables)
        async with AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as session:
            yield session
        await transaction.rollback()
    await engine.dispose()


async def attempt_session(db: AsyncSession) -> str:
    attempt_id = str(uuid4())
    db.add(
        Session(
            id=attempt_id,
            project_id="agent-hub",
            provider="opencode-go",
            model="m",
            status="active",
            session_type="agent",
            request_source="workflow_run",
            provider_metadata={"harness": "agent_hub", "workflow_attempt": {"run_id": "r", "step_key": "s"}},
        )
    )
    await db.commit()
    return attempt_id


def stage(tmp_path: Path, executor: str) -> tuple[str, str]:
    name, native_id = CASES[executor]
    target = tmp_path / executor / name
    target.parent.mkdir(parents=True)
    shutil.copy(FIXTURES / name, target)
    return str(target), native_id


async def kinds(db: AsyncSession, session_id: str) -> Counter[str]:
    rows = await db.execute(select(SessionEvent.event_type).where(SessionEvent.session_id == session_id))
    return Counter(str(getattr(kind, "value", kind)) for (kind,) in rows)


async def count(db: AsyncSession, model: Any, session_id: str) -> int:
    return (await db.execute(select(func.count()).select_from(model).where(model.session_id == session_id))).scalar_one()


# The event types each fixture must produce, counted.
EXPECTED = {
    "pi": {"user_message": 1, "tool_use": 2, "tool_result": 2, "assistant_message": 1, "usage": 3},
    "codex": {
        "user_message": 2, "assistant_message": 2, "tool_use": 2, "tool_result": 2,
        "usage": 2, "usage_counter": 6, "native_lifecycle": 2, "native_settings": 2,
    },
    "claude_code": {"user_message": 1, "assistant_message": 2, "tool_use": 2, "tool_result": 2},
}


@pytest.mark.parametrize("executor", sorted(CASES))
async def test_native_transcript_becomes_events_once(pg_db, tmp_path, executor) -> None:
    attempt_id = await attempt_session(pg_db)
    path, native_id = stage(tmp_path, executor)
    done = await ingest_attempt_transcript(
        pg_db, attempt_id, executor=executor, transcript_path=path, native_session_id=native_id, agent_slug="coder"
    )
    assert done is not None and done["note"] is None and done["events"] > 0
    first = await kinds(pg_db, attempt_id)
    assert first["user_message"] >= 1 and first["assistant_message"] >= 1
    assert first["tool_use"] >= 1 and first["tool_result"] >= 1
    assert dict(first) == EXPECTED[executor]
    named = (await pg_db.execute(select(SessionEvent.agent_id).where(SessionEvent.session_id == attempt_id))).scalars()
    assert set(named) == {"coder"}

    again = await ingest_attempt_transcript(
        pg_db, attempt_id, executor=executor, transcript_path=path, native_session_id=native_id, agent_slug="coder"
    )
    assert again == {"events": 0, "skipped": done["events"] + done["skipped"], "note": None}
    assert await kinds(pg_db, attempt_id) == first
    # Cost belongs to the attempt's own accounting (usage.record_attempt_cost); ingestion adds no rows.
    assert await count(pg_db, CostLog, attempt_id) == 0


async def test_events_follow_the_transcript_order_with_unique_positions(pg_db, tmp_path) -> None:
    attempt_id = await attempt_session(pg_db)
    path, native_id = stage(tmp_path, "pi")
    await ingest_attempt_transcript(
        pg_db, attempt_id, executor="pi", transcript_path=path, native_session_id=native_id
    )
    rows = (
        await pg_db.execute(
            select(SessionEvent.event_type, SessionEvent.turn, SessionEvent.sequence, SessionEvent.tool_name)
            .where(SessionEvent.session_id == attempt_id)
            .order_by(SessionEvent.turn, SessionEvent.sequence)
        )
    ).all()
    assert len({(turn, sequence) for _, turn, sequence, _ in rows}) == len(rows)
    order = [str(getattr(kind, "value", kind)) for kind, *_ in rows if str(getattr(kind, "value", kind)) != "usage"]
    assert order == ["user_message", "tool_use", "tool_result", "tool_use", "tool_result", "assistant_message"]
    assert [name for _, _, _, name in rows if name] == ["write", "write", "bash", "bash"]


async def test_missing_or_unreadable_transcript_is_a_note_not_a_failure(pg_db, tmp_path) -> None:
    attempt_id = await attempt_session(pg_db)
    gone = str(tmp_path / "pi" / "gone.jsonl")
    cases = {
        "recorded no transcript path": dict(transcript_path=None, executor="pi"),
        "no longer on disk": dict(transcript_path=gone, executor="pi"),
        "outside the native transcript folders": dict(transcript_path="/etc/hostname", executor="codex"),
    }
    for phrase, kwargs in cases.items():
        got = await ingest_attempt_transcript(pg_db, attempt_id, native_session_id=PI_ID, **kwargs)
        assert got is not None and got["events"] == 0 and phrase in got["note"], (phrase, got)
    assert await count(pg_db, SessionEvent, attempt_id) == 0

    # A file that is there but is not this session's transcript is reported too, and nothing half-written stays.
    bad = tmp_path / "pi" / "wrong.jsonl"
    bad.parent.mkdir(exist_ok=True)
    bad.write_text(json.dumps({"type": "session", "id": "someone-else"}) + "\n")
    got = await ingest_attempt_transcript(
        pg_db, attempt_id, executor="pi", transcript_path=str(bad), native_session_id=PI_ID
    )
    assert got is not None and got["events"] == 0 and "could not be read" in got["note"]
    assert await count(pg_db, SessionEvent, attempt_id) == 0

    empty = tmp_path / "pi" / "empty.jsonl"
    empty.write_text("")
    got = await ingest_attempt_transcript(
        pg_db, attempt_id, executor="claude_code", transcript_path=str(empty), native_session_id=CLAUDE_ID
    )
    assert got is not None and got["events"] == 0 and got["note"]


async def test_executors_with_their_own_transcript_are_left_alone(pg_db) -> None:
    attempt_id = await attempt_session(pg_db)
    for executor in ("agent_hub", "faux", None):
        assert (
            await ingest_attempt_transcript(
                pg_db, attempt_id, executor=executor, transcript_path="/x", native_session_id=None
            )
            is None
        )


async def test_ingesting_history_moves_no_session_activity_and_adds_nothing_to_the_run(pg_db, tmp_path) -> None:
    """Replayed events are history: the attempt's and run's activity times and live state stay, the run gets no copies."""

    from datetime import UTC, datetime

    then = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    run_id = str(uuid4())
    pg_db.add(
        Session(
            id=run_id, project_id="agent-hub", provider="workflow", model="workflow", status="completed",
            session_type="agent", request_source="workflow_run", last_activity_at=then, updated_at=then,
            provider_metadata={"live_activity": {"phase": "completed", "last_event_type": "child_session_result"}},
        )
    )
    await pg_db.commit()
    attempt_id = str(uuid4())
    live = {"workflow": {"phase": "waiting"}, "phase": "completed", "status": "completed"}
    pg_db.add(
        Session(
            id=attempt_id, project_id="agent-hub", provider="opencode-go", model="m", status="completed",
            session_type="agent", request_source="workflow_run", parent_session_id=run_id,
            last_activity_at=then, updated_at=then, models_used=["m"],
            provider_metadata={"live_activity": live, "workflow_attempt": {"run_id": run_id}},
        )
    )
    await pg_db.commit()
    path, native_id = stage(tmp_path, "pi")
    done = await ingest_attempt_transcript(
        pg_db, attempt_id, executor="pi", transcript_path=path, native_session_id=native_id
    )
    assert done is not None and done["events"] > 0

    await pg_db.rollback()  # read what is stored, not what the session objects remember
    for session_id in (attempt_id, run_id):
        row = (await pg_db.execute(select(Session).where(Session.id == session_id))).scalar_one()
        await pg_db.refresh(row)
        assert (row.last_activity_at, row.updated_at) == (then, then)
    attempt = await pg_db.get(Session, attempt_id)
    assert attempt.provider_metadata["live_activity"] == live and attempt.models_used == ["m"]
    assert await count(pg_db, SessionEvent, run_id) == 0


# --- live following: the transcript is read while the harness writes it ---------------------------------------------

from app.services.workflow_runs.live import LiveStatus  # noqa: E402
from app.services.workflow_runs.live_transcript import TranscriptFollower  # noqa: E402
from app.services.workflow_runs.native_transcript import (  # noqa: E402
    CURSOR_KEY,
    follow_attempt_transcript,
)

ROW_COLUMNS = (
    SessionEvent.event_type, SessionEvent.turn, SessionEvent.sequence, SessionEvent.source_event_id,
    SessionEvent.content, SessionEvent.tool_name, SessionEvent.call_id, SessionEvent.agent_id,
)


async def rows(db: AsyncSession, session_id: str) -> list[tuple[Any, ...]]:
    """What a viewer reads: the session's events in display order (turn, sequence)."""

    found = await db.execute(
        select(*ROW_COLUMNS).where(SessionEvent.session_id == session_id).order_by(SessionEvent.turn, SessionEvent.sequence)
    )
    return [tuple(getattr(v, "value", v) for v in row) for row in found]


def lines_of(executor: str) -> list[bytes]:
    return (FIXTURES / CASES[executor][0]).read_bytes().splitlines(keepends=True)


async def follow(db, attempt_id, executor, path, native_id) -> int:
    return await follow_attempt_transcript(
        db, attempt_id, executor=executor, transcript_path=path, native_session_id=native_id, agent_slug="coder"
    )


@pytest.mark.parametrize("executor", sorted(CASES))
async def test_incremental_ingest_equals_a_one_shot_ingest(pg_db, tmp_path, executor) -> None:
    """The file grows record by record, each with a half-written look first; the final rows are the one-shot rows."""

    live_id, shot_id = await attempt_session(pg_db), await attempt_session(pg_db)
    path, native_id = stage(tmp_path, executor)
    target = Path(path)
    full = target.read_bytes()
    target.write_bytes(b"")  # the harness has not written anything yet
    assert await follow(pg_db, live_id, executor, path, native_id) == 0

    appended = 0
    with target.open("ab") as writer:
        for line in lines_of(executor):
            half = len(line) // 2
            writer.write(line[:half])
            writer.flush()
            before = await count(pg_db, SessionEvent, live_id)
            await follow(pg_db, live_id, executor, path, native_id)  # a record still being written is not read
            assert await count(pg_db, SessionEvent, live_id) == before
            writer.write(line[half:])
            writer.flush()
            appended += await follow(pg_db, live_id, executor, path, native_id)
    assert target.read_bytes() == full and appended > 0

    # The step ends: the final ingest reads the whole file and finds nothing the live passes missed.
    final = await ingest_attempt_transcript(
        pg_db, live_id, executor=executor, transcript_path=path, native_session_id=native_id, agent_slug="coder"
    )
    assert final is not None and final["events"] == 0
    await ingest_attempt_transcript(
        pg_db, shot_id, executor=executor, transcript_path=path, native_session_id=native_id, agent_slug="coder"
    )
    assert await rows(pg_db, live_id) == await rows(pg_db, shot_id)
    assert dict(await kinds(pg_db, live_id)) == EXPECTED[executor]


@pytest.mark.parametrize("executor", sorted(CASES))
async def test_the_final_ingest_adds_only_what_the_live_passes_missed(pg_db, tmp_path, executor) -> None:
    """Live passes stop part way (the worker died, or the file grew after the last tick): the end reconciles."""

    live_id, shot_id = await attempt_session(pg_db), await attempt_session(pg_db)
    path, native_id = stage(tmp_path, executor)
    target = Path(path)
    full = target.read_bytes()
    lines = lines_of(executor)
    target.write_bytes(b"".join(lines[: len(lines) // 2]) + lines[len(lines) // 2][:7])
    first = await follow(pg_db, live_id, executor, path, native_id)
    assert first > 0
    target.write_bytes(full)
    await ingest_attempt_transcript(
        pg_db, live_id, executor=executor, transcript_path=path, native_session_id=native_id, agent_slug="coder"
    )
    await ingest_attempt_transcript(
        pg_db, shot_id, executor=executor, transcript_path=path, native_session_id=native_id, agent_slug="coder"
    )
    assert await rows(pg_db, live_id) == await rows(pg_db, shot_id)


async def test_a_partial_trailing_line_is_skipped_then_picked_up(pg_db, tmp_path) -> None:
    attempt_id = await attempt_session(pg_db)
    path, native_id = stage(tmp_path, "claude_code")
    target = Path(path)
    lines = lines_of("claude_code")
    target.write_bytes(b"".join(lines[:2]) + lines[2][:-1])  # the third record lacks its newline
    first = await follow(pg_db, attempt_id, "claude_code", path, native_id)
    stored = await count(pg_db, SessionEvent, attempt_id)
    assert first == stored > 0
    await follow(pg_db, attempt_id, "claude_code", path, native_id)  # nothing new, nothing doubled
    assert await count(pg_db, SessionEvent, attempt_id) == stored
    target.write_bytes(b"".join(lines[:3]))  # the newline arrives
    assert await follow(pg_db, attempt_id, "claude_code", path, native_id) > 0
    cursor = (await pg_db.get(Session, attempt_id)).provider_metadata[CURSOR_KEY]
    assert cursor["path"] == path and cursor["checkpoint"] and cursor["events"] == await count(pg_db, SessionEvent, attempt_id)


async def test_a_transcript_that_is_not_there_yet_is_nothing_yet(pg_db, tmp_path) -> None:
    attempt_id = await attempt_session(pg_db)
    got = await follow(pg_db, attempt_id, "pi", str(tmp_path / "pi" / "later.jsonl"), PI_ID)
    assert got == 0 and await count(pg_db, SessionEvent, attempt_id) == 0
    assert CURSOR_KEY not in ((await pg_db.get(Session, attempt_id)).provider_metadata or {})


async def test_following_is_history_not_activity_and_writes_no_cost(pg_db, tmp_path) -> None:
    attempt_id = await attempt_session(pg_db)
    path, native_id = stage(tmp_path, "pi")
    before = (await pg_db.get(Session, attempt_id)).last_activity_at
    assert await follow(pg_db, attempt_id, "pi", path, native_id) > 0
    await pg_db.refresh(await pg_db.get(Session, attempt_id))
    assert (await pg_db.get(Session, attempt_id)).last_activity_at == before
    assert await count(pg_db, CostLog, attempt_id) == 0


def factory_of(db: AsyncSession):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def make():
        yield db

    return make


async def test_the_follower_records_the_native_identity_as_soon_as_it_is_known(pg_db, tmp_path) -> None:
    attempt_id = await attempt_session(pg_db)
    path, native_id = stage(tmp_path, "pi")
    live = LiveStatus()
    follower = TranscriptFollower(
        factory_of(pg_db), attempt_id, executor="pi", agent_slug="coder", live=live, interval=60
    )
    assert await follower.sync() == 0  # the harness has said nothing yet
    assert "native_session_id" not in (await pg_db.get(Session, attempt_id)).provider_metadata["workflow_attempt"]
    live.note_native(native_id, locate=lambda: path)  # known from an event; the file is found on the next pass
    assert await follower.sync() > 0
    detail = (await pg_db.get(Session, attempt_id)).provider_metadata["workflow_attempt"]
    assert detail["native_session_id"] == native_id and detail["transcript_path"] == path and detail["executor"] == "pi"
    assert detail["run_id"] == "r"  # the rest of the attempt's record is kept

    done = await follower.finish(transcript_path=path, native_session_id=native_id)
    assert done is not None and done["events"] == 0 and done["skipped"] > 0 and done["note"] is None


async def test_the_follower_tells_an_agent_hub_step_apart(pg_db) -> None:
    """An Agent Hub step has no native file: only its session identity is recorded, and nothing is ingested."""

    attempt_id = await attempt_session(pg_db)
    live = LiveStatus()
    live.note_native(attempt_id)
    follower = TranscriptFollower(
        factory_of(pg_db), attempt_id, executor="agent_hub", agent_slug="coder", live=live, interval=60
    )
    assert await follower.sync() == 0
    detail = (await pg_db.get(Session, attempt_id)).provider_metadata["workflow_attempt"]
    assert detail["native_session_id"] == attempt_id and "transcript_path" not in detail
    assert await follower.finish(transcript_path=None, native_session_id=attempt_id) is None


# --- an Agent Hub step's turns are saved as they happen -------------------------------------------------------------

from app.llm.types import (  # noqa: E402
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
    Usage,
)
from app.services.workflow_runs.agent_hub_transcript import (  # noqa: E402
    Transcript,
    record_transcript,
)

AH_MODEL = "claude-opus-5-5"


def turn(content: list[Any], stop: str = "stop") -> AssistantMessage:
    usage = Usage(input=10, output=5, cache_read=100, cache_write=20, total_tokens=135)
    usage.cost.total = 0.01
    return AssistantMessage(
        content=content, api="claude-code-cli", provider="claude", model=AH_MODEL, usage=usage,
        stop_reason=stop, timestamp=0, response_model=AH_MODEL,
    )


def result_of(call: ToolCall, text: str) -> ToolResultMessage:
    return ToolResultMessage(tool_call_id=call.id, tool_name=call.name, content=[TextContent(text=text)], is_error=False, timestamp=0)


def hub_transcript(session_id: str, turns: list[AssistantMessage], results: dict[str, ToolResultMessage], **kw: Any) -> Transcript:
    return Transcript(
        session_id, "coder", AH_MODEL, input_messages=[{"role": "system", "content": "rules"}, {"role": "user", "content": "goal"}],
        turns=turns, tool_results=results, **kw,
    )


async def save(db: AsyncSession, transcript: Transcript) -> None:
    await record_transcript(db, transcript)
    await db.commit()


async def test_saving_an_agent_hub_transcript_again_adds_only_what_is_new(pg_db) -> None:
    """Pass by pass, as the loop runs, ends with the rows and cost rows of one save of the whole transcript."""

    live_id, shot_id = await attempt_session(pg_db), await attempt_session(pg_db)
    a, b = ToolCall(id="a", name="bash", arguments={"command": "ls"}), ToolCall(id="b", name="bash", arguments={"command": "pwd"})
    first, second = turn([a, b], "toolUse"), turn([TextContent(text="done")])
    results = {"a": result_of(a, "x.txt"), "b": result_of(b, "/w")}

    before = (await pg_db.get(Session, live_id)).last_activity_at
    await save(pg_db, hub_transcript(live_id, [], {}))
    await save(pg_db, hub_transcript(live_id, [first], {}))
    assert await kinds(pg_db, live_id) == Counter(system_message=1, user_message=1, tool_use=2)
    assert await count(pg_db, CostLog, live_id) == 1  # the turn is costed when it is first saved
    await save(pg_db, hub_transcript(live_id, [first], {"a": results["a"]}))
    await save(pg_db, hub_transcript(live_id, [first, second], results))
    final = hub_transcript(live_id, [first, second], results, error=None)
    await save(pg_db, final)  # the end-of-attempt save repeats everything
    await save(pg_db, final)
    await save(pg_db, hub_transcript(shot_id, [first, second], results))

    live, shot = await rows(pg_db, live_id), await rows(pg_db, shot_id)
    normal = lambda rs: sorted((r[0], r[4], r[5], r[6]) for r in rs)  # noqa: E731
    assert normal(live) == normal(shot)  # the same events; only where parallel results fall can differ
    assert await count(pg_db, CostLog, live_id) == await count(pg_db, CostLog, shot_id) == 2
    sources = [r[3] for r in live]
    assert len(sources) == len(set(sources)) and all(sources)
    # History, not activity: saving the conversation moved nothing on the attempt.
    await pg_db.refresh(await pg_db.get(Session, live_id))
    assert (await pg_db.get(Session, live_id)).last_activity_at == before


async def test_a_killed_agent_hub_attempt_keeps_the_turns_it_finished(pg_db, tmp_path) -> None:
    """The worker dies mid-attempt (no final save): the completed turn, its tool result and its cost are stored."""

    import asyncio
    from dataclasses import dataclass, replace

    from app.services.workflow_runs.executor_agent_hub import AgentHubExecutor
    from app.services.workflow_runs.packet import AttemptRef, GitState, build_packet

    attempt_id = await attempt_session(pg_db)
    call = ToolCall(id="t1", name="write_file", arguments={"path": "hello.txt"})
    done_turn = turn([call], "toolUse")

    @dataclass
    class Ev:
        type: str
        message: Any = None
        tool_call: Any = None
        result: Any = None

    async def writer(transcript: Transcript) -> None:
        await save(pg_db, transcript)

    async def hang(**kw: Any) -> Any:
        kw["on_loop_event"](Ev("done", message=done_turn))
        kw["on_loop_event"](Ev("tool_run_complete", tool_call=call, result=result_of(call, "wrote 3 bytes")))
        await asyncio.Event().wait()  # the model's next turn never finishes: the process is killed here

    async def agent(_slug: str) -> Any:
        return type("A", (), {"temperature": 0.3, "thinking_level": "high"})()

    async def tools(_slug: str, _project: str) -> list[dict[str, Any]]:
        return [{"name": "bash"}, {"name": "write_file"}]

    async def on_event(_event: Any) -> None:
        return None

    class Killed(AgentHubExecutor):
        async def _record(self, transcript: Transcript) -> None:
            return None  # a killed process never reaches its end-of-attempt save

    base = build_packet(
        run_goal="goal", step_key="implement", instructions="make it", acceptance=[], git=GitState(), prior_steps=[],
        run_dir="/run", context_window=100_000, budget_fraction=0.25,
    )
    packet = replace(base, attempt=AttemptRef(attempt_id, "run-1", "agent-hub", "coder"))
    executor = Killed(complete=hang, agent_loader=agent, tool_provisioner=tools, transcript_writer=writer)
    wt = tmp_path / "wt"
    wt.mkdir()
    task = asyncio.create_task(executor.run(packet, AH_MODEL, wt, tmp_path, on_event))
    for _ in range(300):
        await asyncio.sleep(0.02)
        if await count(pg_db, SessionEvent, attempt_id) >= 4:
            break
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    stored = await kinds(pg_db, attempt_id)
    assert stored["tool_use"] == 1 and stored["tool_result"] == 1 and stored["user_message"] == 1
    assert await count(pg_db, CostLog, attempt_id) == 1
