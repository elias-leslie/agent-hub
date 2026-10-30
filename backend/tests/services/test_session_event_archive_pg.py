"""PostgreSQL contracts for compacting old finished sessions' events into archives.

An archived session must read back exactly as it did from rows: detail with events, the summary-only
detail, every events window, the events summary and its list row. Runs inside one rolled-back
transaction with private tables in a throwaway schema.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import Enum, Table, func, make_url, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import CreateTable

from app.db import get_db
from app.main import app
from app.models import (
    CostLog,
    Session,
    SessionBinding,
    SessionEvent,
    SessionEventArchive,
    UsageCall,
    UsageSession,
)
from app.models.agent import Agent
from app.services.event_storage import lock_session_event_ingestion, store_event
from app.services.session_event_archive import (
    archive_session_events,
    compact_old_sessions,
    load_archived_events,
)
from tests.conftest import TEST_HEADERS

pytestmark = pytest.mark.integration

OLD = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
SID = "01a00000-0000-7000-8000-00000000a001"


@pytest_asyncio.fixture
async def pg_db() -> AsyncGenerator[AsyncSession]:
    configured = os.environ.get("TEST_AGENT_HUB_DB_URL")
    if not configured:
        pytest.skip("TEST_AGENT_HUB_DB_URL is required")
    url = make_url(configured).set(drivername="postgresql+asyncpg")
    assert url.database and url.database.endswith("_test"), "Archive tests require a test database"
    engine = create_async_engine(url)
    schema = f"event_archive_{uuid4().hex}"
    async with engine.connect() as connection:
        transaction = await connection.begin()
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
        await connection.execute(text(f"SET LOCAL search_path TO {schema}"))

        def create_tables(sync_connection: Any) -> None:
            for table in (Session.__table__, SessionEvent.__table__, SessionEventArchive.__table__, CostLog.__table__,
                          Agent.__table__, UsageCall.__table__, UsageSession.__table__, SessionBinding.__table__):
                for column in table.columns:
                    if isinstance(column.type, Enum):
                        column.type.create(sync_connection, checkfirst=True)
                sync_connection.execute(CreateTable(table, include_foreign_key_constraints=[]))
            for index in cast(Table, SessionEvent.__table__).indexes:  # restore conflicts hit its unique indexes
                index.create(sync_connection)

        await connection.run_sync(create_tables)
        async with AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as session:
            yield session
        await transaction.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def api(pg_db: AsyncSession) -> AsyncGenerator[httpx.AsyncClient]:
    async def override_get_db() -> AsyncGenerator[AsyncSession]:
        yield pg_db

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=TEST_HEADERS) as client:
        yield client
    app.dependency_overrides.pop(get_db, None)


async def add_session(db: AsyncSession, session_id: str, *, status: str = "completed", at: datetime = OLD) -> None:
    db.add(
        Session(
            id=session_id, project_id="agent-hub", provider="codex", model="gpt-test", status=status,
            session_type="agent", provider_metadata={}, models_used=[], created_at=at, updated_at=at,
            last_activity_at=at,
        )
    )
    await db.flush()


def _event(session_id: str, turn: int, sequence: int, event_type: str, **fields: Any) -> SessionEvent:
    return SessionEvent(
        session_id=session_id, turn=turn, sequence=sequence, event_type=event_type,
        created_at=OLD + timedelta(seconds=turn * 100 + sequence), **fields,
    )


async def add_history(db: AsyncSession, session_id: str) -> None:
    db.add_all([
        _event(session_id, 1, 1, "user_message", role="user", content="Fix the flaky\nretention test ✓", tokens=12),
        _event(session_id, 1, 2, "thinking", content="Looking at data_retention.py"),
        _event(session_id, 1, 3, "tool_use", tool_name="Bash", call_id="c1",
               tool_input={"command": "ls -la", "nested": {"a": [1, 2, None]}}, agent_id="helper", agent_name="Helper"),
        _event(session_id, 1, 4, "tool_result", tool_name="Bash", call_id="c1", content="total 0\n",
               tool_output={"output": "total 0\n", "exit_code": 0}),
        _event(session_id, 1, 5, "usage", source_event_id="u1",
               usage={"scope": "response", "source": "codex", "response_id": "r1",
                      "input_tokens": 100, "output_tokens": 20, "cached_input_tokens": 40}),
        _event(session_id, 1, 6, "assistant_message", role="assistant", content="Done: \"quoted\" \\ path", tokens=30,
               model_used="gpt-test", source_timestamp=OLD + timedelta(seconds=107)),
        _event(session_id, 2, 1, "user_message", role="user", content="thanks", tokens=2),
        _event(session_id, 2, 2, "usage_counter", usage={"scope": "turn", "input_tokens": 5}),
    ])
    await db.flush()


async def snapshot(api: httpx.AsyncClient, session_id: str) -> dict[str, Any]:
    async def get(path: str) -> Any:
        response = await api.get(path)
        assert response.status_code == 200, response.text
        return response.json()

    full = await get(f"/api/sessions/{session_id}?include_events=true")
    summary_detail = await get(f"/api/sessions/{session_id}")
    windows = {
        query: await get(f"/api/sessions/{session_id}/events?{query}")
        for query in (
            "", "order=desc", "page_size=3", "page=2&page_size=3", "event_type=tool_use", "turn=2",
            "exclude_types=usage,usage_counter", "q=RETENTION", "q=bash", "order=desc&page_size=2",
        )
    }
    first = await get(f"/api/sessions/{session_id}/events?page_size=3")
    windows["after"] = await get(
        f"/api/sessions/{session_id}/events?page_size=3&after={first['next_after']}&snapshot={first['snapshot']}"
    )
    listing = await get("/api/sessions?sort_by=last_active&sort_direction=desc")
    row = next(item for item in listing["sessions"] if item["id"] == session_id)
    search = await get("/api/sessions?q=flaky")
    later_prompt = await get("/api/sessions?q=thanks")
    for volatile in (full, summary_detail, row):
        volatile.pop("updated_at", None)
    return {
        "full": full,
        "summary_detail": summary_detail,
        "windows": windows,
        "events_summary": await get(f"/api/sessions/{session_id}/events/summary"),
        "list_row": row,
        "search_hits": [item["id"] for item in search["sessions"]],
        "later_prompt_hits": [item["id"] for item in later_prompt["sessions"]],
    }


async def test_archived_session_reads_back_identically(api: httpx.AsyncClient, pg_db: AsyncSession) -> None:
    await add_session(pg_db, SID)
    await add_history(pg_db, SID)
    before = await snapshot(api, SID)
    assert before["full"]["messages"] and before["search_hits"] == before["later_prompt_hits"] == [SID]

    result = await compact_old_sessions(pg_db, older_than_days=30)

    assert (result.sessions, result.events, result.failed, result.skipped) == (1, 8, [], [])
    assert result.stored_bytes < result.raw_bytes
    rows = (await pg_db.execute(select(func.count()).where(SessionEvent.session_id == SID))).scalar()
    assert rows == 0
    archive = await pg_db.get(SessionEventArchive, SID)
    assert archive is not None and archive.event_count == 8 and archive.title == "Fix the flaky retention test ✓"
    pg_db.expunge_all()  # each request reads afresh, as live requests do
    after = await snapshot(api, SID)
    assert after == before


async def test_only_old_finished_sessions_with_events_are_archived(pg_db: AsyncSession) -> None:
    recent = datetime.now(UTC) - timedelta(days=1)
    for session_id, status, at in (
        ("s-active-old", "active", OLD), ("s-recent", "completed", recent), ("s-failed-old", "failed", OLD),
        ("s-empty-old", "completed", OLD),
    ):
        await add_session(pg_db, session_id, status=status, at=at)
        if session_id != "s-empty-old":
            await add_history(pg_db, session_id)

    result = await compact_old_sessions(pg_db, older_than_days=30)

    assert result.sessions == 1
    archived = (await pg_db.execute(select(SessionEventArchive.session_id))).scalars().all()
    assert archived == ["s-failed-old"]
    # Checked again under the lock: a session that picked up work after the listing is left alone.
    assert await archive_session_events(pg_db, "s-active-old", idle_before=datetime.now(UTC)) is None
    assert await archive_session_events(pg_db, "s-recent", idle_before=recent - timedelta(hours=1)) is None


async def test_write_restores_archive_then_rearchive_merges(pg_db: AsyncSession) -> None:
    await add_session(pg_db, SID)
    await add_history(pg_db, SID)
    original = {str(e.id): e for e in (await pg_db.execute(select(SessionEvent))).scalars()}
    assert await archive_session_events(pg_db, SID) is not None
    archived = await load_archived_events(pg_db, SID)
    for event in archived:
        stored = original[str(event.id)]
        for column in SessionEvent.__table__.columns:
            key = "_tool_output" if column.name == "tool_output" else column.name
            assert getattr(event, key) == getattr(stored, key), column.name
    assert archived[3].tool_output == {"output": "total 0\n", "exit_code": 0}

    # Ingestion takes the session lock: the rows come back before it numbers or dedupes anything.
    await lock_session_event_ingestion(pg_db, SID)
    assert await pg_db.get(SessionEventArchive, SID, populate_existing=True) is None
    restored = (await pg_db.execute(select(func.count()).where(SessionEvent.session_id == SID))).scalar()
    assert restored == 8
    await store_event(pg_db, SID, "assistant_message", turn=3, sequence=1, role="assistant", content="later")
    await pg_db.flush()

    archived_again = await archive_session_events(pg_db, SID)
    assert archived_again is not None and archived_again.event_count == 9
    assert [e.content for e in await load_archived_events(pg_db, SID)][-1] == "later"


async def test_restore_keeps_archived_events_whose_ids_are_taken(pg_db: AsyncSession) -> None:
    await add_session(pg_db, SID)
    await add_history(pg_db, SID)
    await archive_session_events(pg_db, SID)
    # A lock-free writer put a row at turn 1 / sequence 1 while the session was archived.
    pg_db.add(_event(SID, 1, 1, "user_message", role="user", content="stray"))
    await pg_db.flush()

    await lock_session_event_ingestion(pg_db, SID)

    # All or nothing: no archived event comes back as a row beside its archive copy.
    assert await pg_db.get(SessionEventArchive, SID, populate_existing=True) is not None
    rows = (await pg_db.execute(select(func.count()).where(SessionEvent.session_id == SID))).scalar()
    assert rows == 1
    assert await archive_session_events(pg_db, SID) is None


async def test_a_session_with_more_events_than_statement_parameters_archives_and_restores(
    pg_db: AsyncSession,
) -> None:
    await add_session(pg_db, SID)
    count = 33_000  # asyncpg allows 32,767 parameters per statement
    await pg_db.execute(
        text(
            "INSERT INTO session_events (session_id, turn, sequence, event_type, content, created_at) "
            "SELECT :sid, g, 1, 'assistant_message', 'line ' || g, CAST(:at AS timestamptz) + g * interval '1 second' "
            "FROM generate_series(1, :n) g"
        ),
        {"sid": SID, "at": OLD, "n": count},
    )

    archived = await archive_session_events(pg_db, SID)

    assert archived is not None and archived.event_count == count
    assert (await pg_db.execute(select(func.count()).where(SessionEvent.session_id == SID))).scalar() == 0
    await lock_session_event_ingestion(pg_db, SID)
    assert (await pg_db.execute(select(func.count()).where(SessionEvent.session_id == SID))).scalar() == count
