"""Persisted-row, reader, replay and reversible migration contracts for tool output."""

from __future__ import annotations

import importlib.util
import json
import os
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session as ORMSession

from app.db import get_db
from app.main import app
from app.models.session import SessionEvent
from app.services.event_storage import _build_session_event
from app.services.memory.summary_transcript import build_condensed_transcript
from app.services.session_branching import copy_events_to_forked_session
from app.services.session_ingestion._events import _process_event, _source_event_fingerprint
from app.services.session_ingestion.adapters.transcript_parsers import parse_transcript_events
from app.services.session_ingestion.models import NormalizedEvent
from app.services.session_queries import SessionEventWindow
from app.services.session_responses import build_event_responses
from tests.conftest import APITestClient


@pytest.fixture
def row_db(tmp_path: Path) -> Generator[ORMSession]:
    # Isolated SQLite is sufficient for real ORM persistence/expiration and JSON
    # response contracts; PostgreSQL migration semantics have a separate test.
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'tool-output.db'}")
    event_table = SessionEvent.__table__
    assert isinstance(event_table, sa.Table)
    event_table.create(engine)
    with ORMSession(engine) as db:
        yield db
    engine.dispose()


def _persist(db: ORMSession, *, content="complete output", tool_output=None, event_type="tool_result") -> SessionEvent:
    payload = {"output": content, "call_id": "native-call", "opaque_blocks": 1, "exit_code": 0} if tool_output is None else tool_output
    event = _build_session_event(
        "session-dedup", 1, 1, event_type, content=content, tool_name="exec",
        call_id="native-call", source_client="pytest", source_event_id="native-event",
        tool_output=payload,
    )
    event.id = str(uuid4())
    event.created_at = datetime.now(UTC)
    db.add(event)
    db.commit()
    db.expire_all()
    return db.scalars(sa.select(SessionEvent)).one()


def test_persisted_text_once_full_response_and_readers(row_db: ORMSession) -> None:
    content = "full unicode output: café\n" + "z" * 100_000 + "\nwarning: retry"
    payload = {"output": content, "call_id": "native-call", "opaque_blocks": 1, "exit_code": 0}
    event = _persist(row_db, content=content, tool_output=payload)
    row = row_db.execute(sa.select(SessionEvent.__table__)).mappings().one()
    assert row["content"] == content
    assert row["tool_output"] == {key: value for key, value in payload.items() if key != "output"}
    assert row["tool_output_from_content"] is True
    assert event.tool_output == payload
    assert payload["output"] == content  # Caller-owned input was not mutated.
    response = build_event_responses([event])[0].model_dump(mode="json")
    assert response["content"] == content
    assert response["tool_output"] == payload
    assert response["source_event_id"] == "native-event"
    assert "tool_output_from_content" not in response
    assert build_condensed_transcript([event]) == f"RESULT: {content[:200]}"


@pytest.mark.parametrize("content,payload,event_type,compact", [
    ("", {"output": "", "is_error": False}, "tool_result", True),
    ("same", {"output": "same"}, "tool_result", True),
    ("same", {"output": "different", "stderr": "error"}, "tool_result", False),
    ("same", {"call_id": "c", "is_error": True}, "tool_result", False),
    (None, {"output": "complete"}, "tool_result", False),
    ("1", {"output": 1}, "tool_result", False),
    ("same", {"output": None}, "tool_result", False),
    ("same", {"output": ["same"]}, "tool_result", False),
    ("same", {"output": "same"}, "tool_audit", False),
])
def test_exact_equality_and_metadata_only_payloads(row_db, content, payload, event_type, compact) -> None:
    event = _persist(row_db, content=content, tool_output=payload, event_type=event_type)
    row = row_db.execute(sa.select(SessionEvent.__table__)).mappings().one()
    assert event.content == content
    assert event.tool_output == payload
    assert row["tool_output_from_content"] is compact
    assert row["tool_output"] == ({key: value for key, value in payload.items() if key != "output"} if compact else payload)


def test_null_output_and_existing_sanitization() -> None:
    event = _build_session_event("s", 1, 1, "tool_result", content="x", tool_output=None)
    assert event.tool_output is None
    assert not event.tool_output_from_content
    event = _build_session_event("s", 1, 1, "tool_result", content="x\x00y", tool_output={"output": "x\x00y", "call_id": "c\x00"})
    assert event.content == "xy"
    assert event._tool_output == {"call_id": "c"}
    assert event.tool_output == {"output": "xy", "call_id": "c"}


def test_orm_replacement_bulk_update_and_stored_column_select(row_db: ORMSession) -> None:
    event = _persist(row_db)
    event_id = event.id
    # Class expressions retain stored JSON semantics, used by existing searches.
    assert row_db.scalar(sa.select(SessionEvent.tool_output)) == event._tool_output
    event.tool_output = {"output": "replacement", "status": "failed"}
    row_db.commit()
    row_db.expire_all()
    loaded = row_db.get(SessionEvent, event_id)
    assert loaded is not None
    assert loaded.tool_output == {"output": "replacement", "status": "failed"}
    assert not loaded.tool_output_from_content
    loaded.tool_output = {"output": loaded.content, "status": "complete"}
    row_db.commit()
    assert loaded.tool_output_from_content
    row_db.execute(sa.update(SessionEvent).where(SessionEvent.id == event_id).values(tool_output={"status": "only metadata"}))
    row_db.commit()
    row_db.expire_all()
    loaded = row_db.get(SessionEvent, event_id)
    assert loaded is not None
    assert loaded.tool_output == {"status": "only metadata"}
    assert not loaded.tool_output_from_content


def test_branch_direct_orm_insert_and_replay_identity(row_db: ORMSession) -> None:
    event = _persist(row_db)
    normalized = NormalizedEvent(
        event_type=event.event_type, content=event.content, tool_name=event.tool_name,
        call_id=event.call_id, tool_output=event.tool_output,
        source_client=event.source_client, source_event_id=event.source_event_id,
    )
    assert _source_event_fingerprint(event, turn=1, sequence=1) == _source_event_fingerprint(normalized, turn=1, sequence=1)
    copy_events_to_forked_session(row_db, [event], "fork-dedup")
    fork = next(row for row in row_db.new if isinstance(row, SessionEvent))
    fork.id = str(uuid4())
    fork.created_at = event.created_at
    row_db.commit()
    row_db.expire_all()
    fork = row_db.scalars(sa.select(SessionEvent).where(SessionEvent.session_id == "fork-dedup")).one()
    assert fork.tool_output == event.tool_output
    assert fork._tool_output == event._tool_output
    assert fork.tool_output_from_content


def test_native_parser_to_persisted_accessor_shape(row_db: ORMSession) -> None:
    parsed = parse_transcript_events([json.dumps({
        "type": "response_item", "payload": {
            "type": "function_call_output", "call_id": "native-call", "output": [
                {"type": "text", "text": "complete output"}, {"type": "image", "data": "opaque"},
            ],
        },
    })])
    native = next(event for event in parsed if event.event_type == "tool_result")
    event = _persist(row_db, content=native.content, tool_output=native.tool_output)
    assert event.tool_output == native.tool_output
    assert event.content == native.content
    assert event._tool_output == {"call_id": "native-call", "opaque_blocks": 1}


@pytest.mark.asyncio
async def test_replayed_native_identity_skips_but_changed_output_fails(row_db: ORMSession) -> None:
    event = _persist(row_db)
    normalized = NormalizedEvent(
        event_type=event.event_type, content=event.content, tool_name=event.tool_name,
        call_id=event.call_id, tool_output=event.tool_output,
        source_client=event.source_client, source_event_id=event.source_event_id,
    )
    db = AsyncMock()
    result = await _process_event(db, event.session_id, normalized, 1, {}, set(), {event.source_event_id: event}, None)
    assert result == (1, 1, None, True)
    assert not db.mock_calls
    with pytest.raises(ValueError, match="replayed with different content"):
        await _process_event(
            db, event.session_id,
            normalized.model_copy(update={"tool_output": {**normalized.tool_output, "output": "different"}}),
            1, {}, set(), {event.source_event_id: event}, None,
        )
    assert not db.mock_calls


def test_actual_events_http_response_from_persisted_row(row_db: ORMSession) -> None:
    event = _persist(row_db)

    async def override_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_db
    with patch("app.api.sessions.get_session_or_404", new=AsyncMock()), patch(
        "app.api.sessions.query_session_event_window",
        new=AsyncMock(return_value=SessionEventWindow(events=[event], total=1, max_turn=1, snapshot="test-snapshot")),
    ):
        response = APITestClient(app).get("/api/sessions/session-dedup/events")
    assert response.status_code == 200
    payload = response.json()["events"][0]
    assert payload["tool_output"] == event.tool_output
    assert payload["content"] == event.content
    assert payload["call_id"] == "native-call"
    assert payload["source_event_id"] == "native-event"
    assert "_tool_output" not in payload
    assert "tool_output_from_content" not in payload


def _migration():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/e0f1a2b3c4d5_deduplicate_tool_result_output.py"
    spec = importlib.util.spec_from_file_location("tool_output_dedup_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_postgres_migration_exact_predicate_and_model_query_compile() -> None:
    migration = _migration()
    query = str(sa.select(migration._events()).where(migration._duplicate_predicate(migration._events())).compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
    ))
    assert "event_type = 'tool_result'" in query
    assert "jsonb_typeof(session_events.tool_output) = 'object'" in query
    assert " = 'string'" in query
    assert "session_events.content = (session_events.tool_output ->> 'output')" in query
    assert "tool_output_from_content IS false" in query
    sql = str(sa.select(SessionEvent).where(sa.cast(SessionEvent.tool_output, sa.String).ilike("%text%")).compile(dialect=postgresql.dialect()))
    assert "CAST(session_events.tool_output AS VARCHAR)" in sql


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt_canonical", [False, True])
async def test_postgres_migration_exact_backfill_and_downgrade(corrupt_canonical: bool) -> None:
    url = os.environ.get("TEST_AGENT_HUB_DB_URL")
    if not url:
        pytest.skip("TEST_AGENT_HUB_DB_URL is required for PostgreSQL migration validation")
    parsed_url = sa.make_url(url)
    assert parsed_url.database == "agent_hub_test", "Only the explicit test database is allowed"
    engine = create_async_engine(parsed_url.set(drivername="postgresql+asyncpg"))
    migration = _migration()

    def verify(connection):
        # A connection-local temporary table shadows the application's table.
        # All DDL and data stay in the explicit test DB and roll back afterward.
        table = sa.Table(
            "session_events", sa.MetaData(), sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("event_type", sa.String), sa.Column("content", sa.Text),
            sa.Column("tool_output", JSONB), sa.Column("source_event_id", sa.String),
            prefixes=["TEMPORARY"],
        )
        table.create(connection)
        fixtures = [
            {"id": 1, "event_type": "tool_result", "content": "café\nfull", "tool_output": {"output": "café\nfull", "call_id": "c", "is_error": False}, "source_event_id": "source-1"},
            {"id": 2, "event_type": "tool_result", "content": "", "tool_output": {"output": ""}, "source_event_id": "source-2"},
            {"id": 3, "event_type": "tool_result", "content": "summary", "tool_output": {"output": "different"}, "source_event_id": "source-3"},
            {"id": 4, "event_type": "tool_result", "content": "metadata", "tool_output": {"call_id": "only"}, "source_event_id": "source-4"},
            {"id": 5, "event_type": "tool_audit", "content": "same", "tool_output": {"output": "same"}, "source_event_id": "source-5"},
            {"id": 6, "event_type": "tool_result", "content": "1", "tool_output": {"output": 1}, "source_event_id": "source-6"},
            {"id": 7, "event_type": "tool_result", "content": None, "tool_output": {"output": "full"}, "source_event_id": "source-7"},
            {"id": 8, "event_type": "tool_result", "content": "null metadata", "tool_output": None, "source_event_id": "source-8"},
            {"id": 9, "event_type": "tool_result", "content": "array metadata", "tool_output": ["array metadata"], "source_event_id": "source-9"},
            {"id": 10, "event_type": "tool_result", "content": "null output", "tool_output": {"output": None}, "source_event_id": "source-10"},
        ]
        connection.execute(table.insert(), fixtures)
        with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
            migration.upgrade()
            flag = sa.column("tool_output_from_content")
            compact = list(connection.execute(sa.select(table, flag).order_by(table.c.id)).mappings())
            assert [row["id"] for row in compact if row["tool_output_from_content"]] == [1, 2]
            assert compact[0]["tool_output"] == {"call_id": "c", "is_error": False}
            assert compact[1]["tool_output"] == {}
            assert compact[0]["content"] == fixtures[0]["content"]
            assert [row["source_event_id"] for row in compact] == [row["source_event_id"] for row in fixtures]
            events = migration._events()
            assert connection.scalar(sa.select(sa.func.count()).select_from(events).where(migration._duplicate_predicate(events))) == 0
            if corrupt_canonical:
                connection.execute(table.update().where(table.c.id == 1).values(content=None))
                with pytest.raises(RuntimeError, match="Cannot restore tool output"):
                    migration.downgrade()
                assert connection.scalar(sa.select(flag).select_from(table).where(table.c.id == 1)) is True
                connection.execute(table.update().where(table.c.id == 1).values(content=fixtures[0]["content"]))
            migration.downgrade()
        restored = list(connection.execute(sa.select(table).order_by(table.c.id)).mappings())
        assert [dict(row) for row in restored] == fixtures

    try:
        async with engine.connect() as connection:
            await connection.run_sync(verify)
            await connection.rollback()
    finally:
        await engine.dispose()
