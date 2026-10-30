"""PostgreSQL contract for batched agent metrics: same numbers as one agent at a time, exact hour buckets.

Runs against the explicit test database inside one rolled-back transaction with
private tables in a throwaway schema, so nothing persists.
"""

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

import app.api.helpers.agent_metrics as agent_metrics
from app.models import CostLog, RequestLog, Session

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def pg_db() -> AsyncGenerator[AsyncSession]:
    configured = os.environ.get("TEST_AGENT_HUB_DB_URL")
    if not configured:
        pytest.skip("TEST_AGENT_HUB_DB_URL is required")
    url = make_url(configured).set(drivername="postgresql+asyncpg")
    assert url.database and url.database.endswith("_test"), "Agent metrics tests require a test database"
    engine = create_async_engine(url)
    schema = f"agent_metrics_{uuid4().hex}"
    async with engine.connect() as connection:
        transaction = await connection.begin()
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
        await connection.execute(text(f"SET LOCAL search_path TO {schema}"))

        def create_tables(sync_connection: Any) -> None:
            for table in (Session.__table__, CostLog.__table__, RequestLog.__table__):
                for column in table.columns:
                    if isinstance(column.type, Enum):
                        column.type.create(sync_connection, checkfirst=True)
                sync_connection.execute(CreateTable(table, include_foreign_key_constraints=[]))

        await connection.run_sync(create_tables)
        async with AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as session:
            yield session
        await transaction.rollback()
    await engine.dispose()


def _request(slug: str, age: timedelta, *, latency: int, status: int = 200) -> RequestLog:
    return RequestLog(
        endpoint="/api/complete", method="POST", status_code=status, latency_ms=latency,
        tokens_in=10, tokens_out=5, agent_slug=slug, created_at=NOW - age,
    )


@pytest.mark.asyncio
async def test_batched_metrics_bucket_hour_boundaries_into_the_newer_hour(
    pg_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Frozen(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return NOW

    monkeypatch.setattr(agent_metrics, "datetime", Frozen)
    pg_db.add_all([
        _request("coder", timedelta(minutes=30), latency=100),
        _request("coder", timedelta(hours=1), latency=300, status=500),  # boundary: the newest hour
        _request("coder", timedelta(hours=1, minutes=1), latency=500),
        _request("coder", timedelta(hours=24), latency=700),  # oldest bucket's start, counted in both
        _request("coder", timedelta(hours=25), latency=900),  # outside the day
        _request("reviewer", timedelta(minutes=5), latency=50),
    ])
    pg_db.add(Session(id="s1", project_id="p", provider="claude", model="m", agent_slug="coder"))
    await pg_db.flush()
    pg_db.add(CostLog(session_id="s1", model="m", input_tokens=1, output_tokens=1, cost_usd=1.25,
                      created_at=NOW - timedelta(hours=2)))
    await pg_db.flush()

    metrics = await agent_metrics.compute_agents_metrics(pg_db, ["coder", "reviewer", "idle"])

    coder = metrics["coder"]
    assert coder.requests_24h == 4
    assert coder.avg_latency_ms == pytest.approx(400)
    assert coder.success_rate == pytest.approx(75)
    assert coder.tokens_24h == 60
    assert coder.cost_24h_usd == pytest.approx(1.25)
    assert coder.latency_trend[-1] == pytest.approx(200)
    assert coder.success_trend[-1] == pytest.approx(50)
    assert coder.latency_trend[-2] == 500
    assert coder.success_trend[-2] == 100
    assert coder.latency_trend[0] == 700
    assert sum(1 for value in coder.latency_trend if value) == 3
    assert metrics["reviewer"].latency_trend[-1] == 50
    assert metrics["idle"].requests_24h == 0
    assert metrics["idle"].latency_trend == [0.0] * 24
    assert (await agent_metrics.compute_agent_metrics(pg_db, "coder")) == coder
