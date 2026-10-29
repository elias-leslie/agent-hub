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
