"""PostgreSQL contracts for the Context pages' read endpoints: matrix, trend and cell, through the real router.

Same throwaway-schema setup as the `why` tests (tables from the models, the markers view from the migration).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Memory, UsageSession
from app.models.memory_unified import MemoryRevision
from app.services.context_observability import views
from tests.services import test_context_why_pg as why_tests
from tests.services.test_context_why_pg import NOW, STEP_AT, _block, _delivery, _policy, _session

db = why_tests.db  # the throwaway-schema fixture, shared with the `why` tests

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def client(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[AsyncClient]:
    from fastapi import FastAPI

    from app.api.context_observability import router
    from app.db import get_db
    from app.services.api_key_auth import require_api_key

    # The routes read "now" from the clock; the data is pinned to NOW, so the clock is too.
    real_matrix, real_trend, real_cell = views.matrix, views.trend, views.cell
    monkeypatch.setattr(views, "matrix", lambda db, *, days, now=None: real_matrix(db, days=days, now=NOW))
    monkeypatch.setattr(views, "trend", lambda db, h, r, *, days, now=None: real_trend(db, h, r, days=days, now=NOW))
    monkeypatch.setattr(views, "cell", lambda db, h, r, *, now=None: real_cell(db, h, r, now=NOW))
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_api_key] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def _lane_step(db: AsyncSession, memory_id: str) -> None:
    db.add_all([_delivery("d-old", STEP_AT - timedelta(days=1), [_block("keep", 1000), _block(memory_id, 200)]),
                _delivery("d-new", STEP_AT, [_block("keep", 1000), _block(memory_id, 1400, "r2")])])
    db.add(MemoryRevision(
        memory_uuid=memory_id, version=2, action="update", content="x", name="Test with Haiku agents", memory_type="reference", scope="global",
        tier=2, pinned=False, auto_inject=False, display_order=50, status="active", content_hash="h", token_count=1400,
        changed_by="client:abc", writer_kind="agent", writer_session="aico-widget-lane", created_at=STEP_AT - timedelta(minutes=20)))
    for i in range(20):
        db.add(_session(i, STEP_AT - timedelta(hours=10) + timedelta(minutes=20 * i), 30000, delivery="d-old", ours=1200, harness_tokens=28700))
    for i in range(6):
        db.add(_session(100 + i, STEP_AT + timedelta(minutes=10 * i), 42000, delivery="d-new", ours=2700, harness_tokens=39200, version="2.1.317"))
    await _policy(db)
    await db.flush()


async def test_matrix_lists_each_cell_with_its_split_and_leaves_unmeasured_values_null(db: AsyncSession, client: AsyncClient) -> None:
    await _lane_step(db, str(uuid.uuid4()))

    body = (await client.get("/api/context-observability/matrix", params={"days": 7})).json()

    (cell,) = body["cells"]
    assert (cell["harness"], cell["cell"], cell["n"], cell["total"], cell["ours"]) == ("claude", "implementation", 26, 30000, 1200)
    assert cell["delta"] is None and cell["warn_tokens"] == 60000 and cell["flag"] is None  # nothing before the window to compare with
    assert [(h["harness"], h["version"]) for h in body["harnesses"]] == [("claude", "2.1.317")]
    assert body["jump_pct"] == 25 and body["coverage_from"] is not None


async def test_trend_returns_points_daily_medians_versions_and_the_step_with_the_cause_from_why(db: AsyncSession, client: AsyncClient) -> None:
    await _lane_step(db, str(uuid.uuid4()))

    body = (await client.get("/api/context-observability/trend", params={"harness": "claude", "role": "implementation", "days": 7})).json()

    assert body["points_total"] == 26 and len(body["points"]) == 26 and body["warn_tokens"] == 60000
    assert [(d["day"], d["n"]) for d in body["daily"]] == [("2026-11-01", 26)]
    assert [(v["version"], v["initial"]) for v in body["versions"]] == [("2.1.316", True), ("2.1.317", False)]
    (step,) = body["steps"]
    assert (step["kind"], step["cause"], step["before_total"], step["after_total"]) == ("version", "harness_version", 30000, 42000)
    assert "claude implementation" in step["summary"] and step["parts"]["harness"] == 10500
    assert any(m["kind"] == "harness_version" for m in step["markers"])
    # an unknown cell is an empty answer, not an error and not zeros
    empty = (await client.get("/api/context-observability/trend", params={"harness": "pi", "role": "x", "days": 7})).json()
    assert (empty["points"], empty["steps"], empty["headline"]["total"], empty["latest_at"]) == ([], [], None, None)


async def test_cell_has_the_latest_start_its_blocks_with_the_last_writer_growth_and_the_newest_move(db: AsyncSession, client: AsyncClient) -> None:
    memory_id = str(uuid.uuid4())
    db.add(Memory(id=memory_id, content="x", name="learning_1", summary="Test with Haiku agents", memory_type="reference", scope="global"))
    await _lane_step(db, memory_id)
    latest = (await db.execute(select(UsageSession).where(UsageSession.session_id == "s105"))).scalar_one()
    latest.peak_context_tokens, latest.compaction_count = 180000, 1
    await db.flush()

    resp = await client.get("/api/context-observability/cell", params={"harness": "claude", "role": "implementation"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert (body["latest"]["total"], body["latest"]["session_id"], body["delivery_id"]) == (42000, "s105", "d-new")
    assert body["parts"]["ours"]["tokens"] == 2700 and "harness_tools" not in body["parts"]  # a part that was not stored is absent
    blocks = {b["source_id"]: b for b in body["blocks"]}
    assert [b["tokens"] for b in body["blocks"]] == [1400, 1000] and body["blocks_total"] == 2400
    grown = blocks[memory_id]
    assert (grown["label"], grown["writer_session"], grown["writer_kind"], grown["writer_action"]) == ("Test with Haiku agents", "aico-widget-lane", "agent", "update")
    assert blocks["keep"]["writer_at"] is None  # no revision in the last 30 days: unknown, not "nobody"
    assert body["growth"] == {"sessions": 26, "measured": 1, "median_peak": 180000, "max_peak": 180000, "median_first_turn": 42000,
                              "compacted": 1, "compactions": 1}
    assert body["budget_warn"] == 60000 and body["latest_move"]["cause"] == "harness_version"
    assert [r["session_id"] for r in body["recent"]][:2] == ["s105", "s104"] and len(body["recent"]) == 10

    none = (await client.get("/api/context-observability/cell", params={"harness": "codex", "role": "review"})).json()
    assert (none["latest"], none["blocks"], none["blocks_total"], none["growth"]["measured"]) == (None, [], None, 0)
