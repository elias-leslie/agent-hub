"""PostgreSQL contracts for run history's status filter and the profiles' unreviewed-failure count.

Runs against the explicit test database inside one rolled-back transaction with
private tables in a throwaway schema, so nothing persists.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import CreateTable

from app.api.automations import _profile
from app.db import get_db
from app.main import app
from app.models import (
    AutomationDefinition,
    AutomationProfile,
    AutomationProjectPolicy,
    AutomationRun,
)
from tests.conftest import TEST_HEADERS

pytestmark = pytest.mark.integration

BASE = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def pg_db() -> AsyncGenerator[AsyncSession]:
    configured = os.environ.get("TEST_AGENT_HUB_DB_URL")
    if not configured:
        pytest.skip("TEST_AGENT_HUB_DB_URL is required")
    url = make_url(configured).set(drivername="postgresql+asyncpg")
    assert url.database and url.database.endswith("_test"), "Automation run tests require a test database"
    engine = create_async_engine(url)
    schema = f"automation_runs_{uuid4().hex}"
    async with engine.connect() as connection:
        transaction = await connection.begin()
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
        await connection.execute(text(f"SET LOCAL search_path TO {schema}"))

        def create_tables(sync_connection: Any) -> None:
            for table in (AutomationDefinition.__table__, AutomationProjectPolicy.__table__,
                          AutomationProfile.__table__, AutomationRun.__table__):
                sync_connection.execute(CreateTable(table, include_foreign_key_constraints=[]))

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


async def _seed(db: AsyncSession, statuses: list[str], reviewed_at: datetime | None = None) -> AutomationProfile:
    db.add(AutomationDefinition(
        workflow_key="agent-hub.session_cleanup", version=1, owner_project_id="agent-hub", label="Session cleanup",
        description="", dispatch_kind="internal", dispatch_target="session_cleanup", config_schema={},
        policy_schema={}, default_schedule={}, overlap_strategy="CANCEL_NEWEST",
    ))
    profile = AutomationProfile(
        id=str(uuid4()), project_id="agent-hub", workflow_key="agent-hub.session_cleanup", definition_version=1,
        label="Session cleanup", schedule_type="cron", schedule_value="*/15 * * * *", schedule_timezone="UTC",
        config={}, enabled=True, clock_owner="central", owner_gate_reasons=[], revision=1,
        imported_unreviewed_count=0, last_reviewed_at=reviewed_at,
    )
    db.add(profile)
    for minute, status in enumerate(statuses):
        at = BASE + timedelta(minutes=minute)
        db.add(AutomationRun(
            id=str(uuid4()), profile_id=profile.id, project_id="agent-hub", workflow_key=profile.workflow_key,
            definition_version=1, profile_revision=1, trigger="scheduled",
            occurrence_key=f"scheduled:{profile.id}:{at.isoformat()}", scheduled_for=at, status=status,
            gate_reasons=[], config_snapshot={}, policy_snapshot={}, owner_receipt={}, created_at=at,
        ))
    await db.flush()
    return profile


async def test_runs_filter_by_status_counts_before_paging(api: httpx.AsyncClient, pg_db: AsyncSession) -> None:
    await _seed(pg_db, ["succeeded", "failed", "succeeded", "rejected", "failed", "succeeded"])

    everything = (await api.get("/api/automations/runs")).json()
    assert everything["total"] == 6

    failed = await api.get("/api/automations/runs", params={"status": "failed", "limit": 1})
    assert failed.status_code == 200
    body = failed.json()
    assert body["total"] == 2
    assert [run["status"] for run in body["items"]] == ["failed"]
    assert body["items"][0]["created_at"].startswith("2026-10-01T12:04")

    either = (await api.get("/api/automations/runs", params=[("status", "failed"), ("status", "rejected")])).json()
    assert sorted(run["status"] for run in either["items"]) == ["failed", "failed", "rejected"]


async def test_unreviewed_count_is_failures_since_last_review(pg_db: AsyncSession) -> None:
    profile = await _seed(
        pg_db, ["failed", "succeeded", "succeeded", "failed", "rejected", "succeeded"],
        reviewed_at=BASE + timedelta(minutes=1),
    )

    shown = await _profile(pg_db, profile)

    assert shown["unreviewed_count"] == 1
