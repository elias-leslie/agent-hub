"""PostgreSQL contracts for the per-root context size `st aico roots` shows: matching, measuring, unknown instead of 0."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import Enum, make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import CreateTable

from app.models import Session, SessionEvent, UsageCall
from app.services.context_observability import aico_roots

pytestmark = pytest.mark.integration

BASE = datetime(2026, 11, 1, 12, tzinfo=UTC)


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession]:
    configured = os.environ.get("TEST_AGENT_HUB_DB_URL")
    if not configured:
        pytest.skip("TEST_AGENT_HUB_DB_URL is required")
    url = make_url(configured).set(drivername="postgresql+asyncpg")
    assert url.database and url.database.endswith("_test")
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        schema = f"aico_roots_{uuid4().hex}"
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
        await connection.execute(text(f"SET LOCAL search_path TO {schema}"))

        def create_tables(sync_connection: Any) -> None:
            for table in (Session.__table__, SessionEvent.__table__, UsageCall.__table__):
                for column in table.columns:
                    if isinstance(column.type, Enum):
                        column.type.create(sync_connection, checkfirst=True)
                sync_connection.execute(CreateTable(table, include_foreign_key_constraints=[]))

        await connection.run_sync(create_tables)
        async with AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            yield session
        await transaction.rollback()
    await engine.dispose()


def _session(sid: str, metadata: dict[str, Any], *, minutes: int = 0, parent: str | None = None, session_type: str = "claude_code") -> Session:
    return Session(id=sid, project_id="p", provider="anthropic", model="claude-opus-5-5", status="active", session_type=session_type,
                   parent_session_id=parent, provider_metadata=metadata, last_activity_at=BASE + timedelta(minutes=minutes))


def _call(key: str, sid: str, minutes: int, inp: int, read: int, write: int, agent: str = "") -> UsageCall:
    return UsageCall(call_key=key, occurred_at=BASE + timedelta(minutes=minutes), provider="claude", session_id=sid, agent_id=agent,
                     model="claude-opus-5-5", input_tokens=inp, cached_input_tokens=read, cache_write_tokens=write, output_tokens=5)


def _bound(root: str) -> dict[str, Any]:
    return {"work_role": {"id": "coordinator", "source": f"tether:root:{root}"}}


async def test_a_root_shows_the_newest_main_chain_calls_context(db: AsyncSession) -> None:
    db.add(_session("s1", _bound("aico-root-a")))
    await db.flush()
    db.add_all([_call("c1", "s1", 1, 2, 90_000, 500), _call("c2", "s1", 2, 3, 211_525, 433),
                _call("c3", "s1", 3, 2, 9_000, 0, agent="sub")])  # a sub-agent call is not the root's context
    await db.flush()

    result = await aico_roots.latest_context(db, ["aico-root-a"])

    assert result["aico-root-a"].context_tokens == 211_961
    assert result["aico-root-a"].session_id == "s1"


async def test_a_root_with_no_session_or_no_usage_is_left_out_never_zero(db: AsyncSession) -> None:
    db.add_all([_session("s1", _bound("aico-root-quiet")), _session("s2", _bound("aico-root-zero"))])
    await db.flush()
    db.add(_call("z", "s2", 1, 0, 0, 0))
    await db.flush()

    result = await aico_roots.latest_context(db, ["aico-root-quiet", "aico-root-zero", "aico-root-unknown"])

    assert result == {}


async def test_the_newest_session_of_a_root_wins_and_children_never_match(db: AsyncSession) -> None:
    db.add_all([_session("old", _bound("aico-root-a"), minutes=1), _session("new", _bound("aico-root-a"), minutes=9),
                _session("kid", _bound("aico-root-a"), minutes=20, parent="new")])
    await db.flush()
    db.add_all([_call("o", "old", 1, 1, 50_000, 0), _call("n", "new", 9, 1, 12_000, 0), _call("k", "kid", 20, 1, 99_000, 0)])
    await db.flush()

    result = await aico_roots.latest_context(db, ["aico-root-a"])

    assert (result["aico-root-a"].session_id, result["aico-root-a"].context_tokens) == ("new", 12_001)


async def test_a_pi_session_is_matched_by_its_aico_session_id_and_read_from_its_response_usage(db: AsyncSession) -> None:
    db.add(_session("pi1", {"aico_session_id": "aico-widget-ab12cd34"}, session_type="pi"))
    await db.flush()
    for turn, total in enumerate((20_000, 26_881)):
        db.add(SessionEvent(session_id="pi1", turn=turn, sequence=0, event_type="usage", created_at=BASE + timedelta(minutes=turn),
                            usage={"scope": "response", "input_tokens": total, "cached_input_tokens": total - 400}))
    db.add(SessionEvent(session_id="pi1", turn=9, sequence=0, event_type="usage", created_at=BASE + timedelta(minutes=9),
                        usage={"scope": "thread", "input_tokens": 9_000_000}))  # a running total is not a context size
    await db.flush()

    result = await aico_roots.latest_context(db, ["aico-root-x", "aico-widget-ab12cd34"])

    assert list(result) == ["aico-widget-ab12cd34"]
    assert result["aico-widget-ab12cd34"].context_tokens == 26_881


async def test_the_api_serves_the_batched_read(db: AsyncSession) -> None:
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api.context_observability import router
    from app.db import get_db
    from app.services.api_key_auth import require_api_key

    db.add(_session("s1", _bound("aico-root-a")))
    await db.flush()
    db.add(_call("c1", "s1", 1, 2, 100_000, 0))
    await db.flush()
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_api_key] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.get("/api/context-observability/aico-roots", params={"keys": "aico-root-a,aico-root-b"})

    assert response.status_code == 200
    assert list(response.json()["roots"]) == ["aico-root-a"]
    assert response.json()["roots"]["aico-root-a"]["context_tokens"] == 100_002
