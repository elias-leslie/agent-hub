"""PostgreSQL contract for the refusal read behind the launch table's "last refusal"."""

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

from app.models import Session, SessionEvent
from app.routing import launch_facts

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
        schema = f"launch_facts_{uuid4().hex}"
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
        await connection.execute(text(f"SET LOCAL search_path TO {schema}"))

        def create_tables(sync_connection: Any) -> None:
            for table in (Session.__table__, SessionEvent.__table__):
                for column in table.columns:
                    if isinstance(column.type, Enum):
                        column.type.create(sync_connection, checkfirst=True)
                sync_connection.execute(CreateTable(table, include_foreign_key_constraints=[]))

        await connection.run_sync(create_tables)
        async with AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            yield session
        await transaction.rollback()
    await engine.dispose()


def _refusal(index: int, minutes: int) -> SessionEvent:
    return SessionEvent(session_id="s1", turn=index, sequence=index, event_type="error", created_at=BASE + timedelta(minutes=minutes),
                        usage={"provider_outcome": {"kind": "refused", "requested_model": f"model-{index}"}})


async def test_refusals_are_newest_first_and_capped(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launch_facts, "REFUSAL_ROWS", 2)
    db.add(Session(id="s1", project_id="p", provider="anthropic", model="m", status="completed", session_type="claude_code"))
    await db.flush()
    # Inserted oldest, newest, middle: heap order is neither of the orders asked for.
    db.add_all([_refusal(1, 0), _refusal(3, 30), _refusal(2, 10)])
    await db.flush()

    rows = await launch_facts._refusals(db)

    assert [row["requested_model"] for row in rows] == ["model-3", "model-2"]
