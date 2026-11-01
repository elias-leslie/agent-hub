"""PostgreSQL contracts for markers, `why`, and the two Nightshift items.

Runs against the explicit test database in a throwaway schema (tables from the models, the markers view from the
migration). Nightshift is never called: send and resolve are replaced by recorders.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Enum, make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import CreateTable

from app.models import (
    ContextBudget,
    ContextDelivery,
    ContextKnob,
    SubscriptionUsageCursor,
    UsageSession,
)
from app.models.agent import Agent
from app.models.context_change_review import ContextChangeReview
from app.models.context_governance import ContextRecord
from app.models.memory_unified import Memory, MemoryRevision
from app.models.prompt import Prompt, PromptRevision
from app.models.runtime_context import RuntimeContextOverride
from app.services.context_observability import alerts
from app.services.context_observability import why as why_service
from app.services.context_observability.budgets import cell_states
from app.services.context_observability.markers import view_markers
from app.services.context_observability.policy import load_policy

pytestmark = pytest.mark.integration

MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "a7c3e9d41b52_context_budgets_knobs_markers.py"
NOW = datetime(2026, 11, 1, 18, tzinfo=UTC)
STEP_AT = datetime(2026, 11, 1, 14, 53, 44, tzinfo=UTC)


def _migration() -> Any:
    spec = importlib.util.spec_from_file_location("context_markers_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_tables(sync_connection: Any) -> None:
    tables = (Agent.__table__, Memory.__table__, MemoryRevision.__table__, Prompt.__table__, PromptRevision.__table__,
              ContextRecord.__table__, RuntimeContextOverride.__table__, ContextChangeReview.__table__, ContextDelivery.__table__,
              UsageSession.__table__, ContextBudget.__table__, ContextKnob.__table__, SubscriptionUsageCursor.__table__)
    fks = (Memory.__table__, MemoryRevision.__table__, PromptRevision.__table__)
    for table in tables:
        for column in table.columns:
            if isinstance(column.type, Enum):
                column.type.create(sync_connection, checkfirst=True)
        sync_connection.execute(CreateTable(table, include_foreign_key_constraints=None if table in fks else []))
    sync_connection.execute(text(_migration().MARKERS_VIEW_SQL))


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
        await connection.execute(text(f"CREATE SCHEMA ctx_why_{uuid.uuid4().hex}"))
        schema = (await connection.execute(text("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'ctx_why_%' ORDER BY oid DESC LIMIT 1"))).scalar_one()
        await connection.execute(text(f"SET LOCAL search_path TO {schema}, public"))
        await connection.run_sync(_create_tables)
        async with AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            yield session
        await transaction.rollback()
    await engine.dispose()


def _sent(mock: AsyncMock) -> Any:
    """First argument of the latest call."""
    assert mock.await_args is not None
    return mock.await_args.args[0]


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    send, resolve = AsyncMock(return_value=True), AsyncMock(return_value=True)
    monkeypatch.setattr("app.services.owner_notice.send_notice", send)
    monkeypatch.setattr("app.services.owner_notice.resolve_notice", resolve)
    return {"send": send, "resolve": resolve}


async def _policy(db: AsyncSession, *, knob_repo: Path | None = None, warn: int = 60000, jump: int = 25) -> None:
    db.add(ContextBudget(harness="*", role="*", warn_tokens=warn, jump_pct=jump))
    if knob_repo is not None:
        db.add(ContextKnob(name="lane-tools.json", harness="claude", role="*", repo_path=str(knob_repo), file_path="lane-tools.json"))
    await db.flush()


def _git_repo(path: Path, *commit_times: datetime) -> Path:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    for i, when in enumerate(commit_times):
        (path / "lane-tools.json").write_text(f'{{"v": {i}}}')
        stamp = {**env, "GIT_AUTHOR_DATE": when.isoformat(), "GIT_COMMITTER_DATE": when.isoformat()}
        subprocess.run(["git", "-C", str(path), "add", "."], check=True)
        subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", f"lane tools {i}"], check=True, env=stamp)
    return path


def _delivery(delivery_id: str, at: datetime, blocks: list[dict[str, Any]], role: str = "implementation") -> ContextDelivery:
    return ContextDelivery(delivery_id=delivery_id, generated_at=at, source="api", surface="claude_code", profile="agent_startup",
                           project_id="agent-hub", session_id="aico-widget-x", work_role=role, coordinator=False, consumer_tags=[],
                           est_tokens=sum(b["tokens"] for b in blocks), payload_hash=delivery_id.ljust(64, "0"), rendered_chars=100,
                           by_scope={}, blocks=blocks)


def _block(source_id: str, tokens: int, revision: str = "r1", source_type: str = "memory") -> dict[str, Any]:
    return {"block_id": f"b-{source_id}", "kind": "guardrail", "source_type": source_type, "source_id": source_id,
            "revision": revision, "scope": "global", "tokens": tokens}


def _session(i: int, at: datetime, total: int, *, delivery: str | None = None, fp: str = "fp-a", version: str = "2.1.316",
             harness_tokens: int | None = None, ours: int = 5000, role: str = "implementation", model: str = "claude-opus-5-5") -> UsageSession:
    return UsageSession(
        provider="claude", session_id=f"s{i}", agent_id="", first_at=at, last_at=at, harness="claude", harness_version=version,
        work_role=role, coordinator=False, launch_mode="project", model=model, first_turn_tokens=total, first_turn_at=at,
        parts={"harness": {"tokens": harness_tokens if harness_tokens is not None else total - ours - 100}, "ours": {"tokens": ours},
               "brief": {"tokens": 100}, "total": {"tokens": total}},
        delivery_id=delivery, config_fp=fp)


async def _replay_1101(db: AsyncSession, repo: Path) -> None:
    """The 2026-11-01 lane step: 48.4K to 24.0K at 14:53:44Z on Claude Code 2.1.316 with one fingerprint change."""
    db.add_all([_delivery("d-old", STEP_AT - timedelta(days=1), [_block("m1", 2000)]),
                _delivery("d-new", STEP_AT, [_block("m1", 2000)])])
    for i in range(40):
        db.add(_session(i, STEP_AT - timedelta(hours=14) + timedelta(minutes=15 * i), 48400, delivery="d-old"))
    for i in range(6):
        db.add(_session(100 + i, STEP_AT + timedelta(minutes=30 * i), 24000, delivery="d-new", fp="fp-b", harness_tokens=24000 - 5100))
    await _policy(db, knob_repo=repo)
    await db.flush()


async def test_why_names_the_lane_step_as_the_config_change_and_its_knob(db: AsyncSession, tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "aico", datetime(2026, 11, 1, 14, 41, 38, tzinfo=UTC), datetime(2026, 11, 1, 14, 53, 24, tzinfo=UTC))
    await _replay_1101(db, repo)

    result = await why_service.why(db, "claude", "lane", now=NOW)

    assert result.before is not None and result.after is not None
    assert (result.kind, result.cause, result.at) == ("config", "config", STEP_AT)
    assert (result.before.total, result.after.total, result.delta) == (48400, 24000, -24400)
    assert (result.version["from"], result.version["to"]) == ("2.1.316", "2.1.316")
    assert (result.config_fp["from"], result.config_fp["to"]) == ("fp-a", "fp-b")
    assert result.parts["harness"] == -24400 + 0 and result.parts["ours"] == 0
    assert sorted({k.label for k in result.knobs}) == ["lane-tools.json"] and len(result.knobs) == 2
    assert "lane-tools.json" in result.summary and "cause config" in result.summary and "2.1.316 unchanged" in result.summary
    config = [m for m in result.markers if m.kind == "config"]
    assert [(m.at, m.detail["from_fp"], m.ref) for m in config] == [(STEP_AT, "fp-a", "fp-b")]
    assert [m.kind for m in result.markers if m.kind == "knob"] == ["knob", "knob"]


async def test_a_change_with_no_knob_changed_and_a_new_version_is_blamed_on_the_harness_version(db: AsyncSession, tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "aico", datetime(2026, 10, 1, 9, tzinfo=UTC))  # long before the step
    for i in range(20):
        db.add(_session(i, STEP_AT - timedelta(days=2) + timedelta(hours=i), 42000))
    for i in range(6):
        db.add(_session(100 + i, STEP_AT + timedelta(hours=i), 48800, version="2.1.318", fp="fp-b"))
    await _policy(db, knob_repo=repo)
    await db.flush()

    result = await why_service.why(db, "claude", "implementation", now=NOW)

    assert (result.cause, result.knobs) == ("harness_version", [])
    assert (result.version["from"], result.version["to"]) == ("2.1.316", "2.1.318")
    assert result.parts["harness"] == 6800 and result.parts["ours"] == 0


async def test_a_step_where_the_model_the_fingerprint_and_the_version_all_changed_is_not_blamed_on_the_larger_part(
        db: AsyncSession, tmp_path: Path) -> None:
    """claude subagent:general-purpose, 2026-10-31 13:14Z: sonnet to opus, fp 6952085d to 97c3f89f, 2.1.314 to 2.1.316,
    harness +5.4K and ours +5.9K. The old code said "ours" by size alone."""
    repo = _git_repo(tmp_path / "aico", datetime(2026, 10, 1, 9, tzinfo=UTC))
    cell = "subagent:general-purpose"
    rows = [_session(i, STEP_AT - timedelta(days=2) + timedelta(hours=i), 35000, model="claude-sonnet-5-5", version="2.1.314", fp="fp-a")
            for i in range(12)]
    rows += [_session(100 + i, STEP_AT - timedelta(days=1) + timedelta(hours=i), 30000, ours=4000, harness_tokens=25900, version="2.1.314", fp="fp-a")
             for i in range(8)]
    rows += [_session(200 + i, STEP_AT + timedelta(hours=i), 41300, ours=9900, harness_tokens=31300, version="2.1.316", fp="fp-b")
             for i in range(6)]
    for row in rows:
        row.launch_mode, row.work_role = cell, "implementation"
    db.add_all(rows)
    await _policy(db, knob_repo=repo)
    await db.flush()

    result = await why_service.why(db, "claude", cell, now=NOW)

    assert (result.parts["harness"], result.parts["ours"]) == (5400, 5900) and result.delta == 11300
    assert result.cause == "mixed"
    assert result.changed == ["model", "config_fp", "version"]
    assert "Changed together: model, config_fp, version" in result.summary
    assert result.before is not None and result.before.model == "claude-opus-5-5"  # compared on one model only


async def test_a_grown_block_is_named_with_the_session_that_wrote_it(db: AsyncSession, tmp_path: Path) -> None:
    memory_id = str(uuid.uuid4())
    db.add_all([_delivery("d-old", STEP_AT - timedelta(days=1), [_block("keep", 1000), _block(memory_id, 200)]),
                _delivery("d-new", STEP_AT, [_block("keep", 1000), _block(memory_id, 1400, "r2"), _block("added", 300, source_type="prompt")])])
    db.add(MemoryRevision(
        memory_uuid=memory_id, version=2, action="update", content="x", name="Test with Haiku agents", memory_type="reference",
        scope="global", tier=2, pinned=False, auto_inject=False, display_order=50, status="active", content_hash="h", token_count=1400,
        changed_by="client:abc", writer_kind="agent", writer_session="aico-widget-lane", created_at=STEP_AT - timedelta(minutes=20)))
    for i in range(20):
        db.add(_session(i, STEP_AT - timedelta(hours=10) + timedelta(minutes=20 * i), 30000, delivery="d-old", ours=1200, harness_tokens=28700))
    for i in range(4):
        db.add(_session(100 + i, STEP_AT + timedelta(minutes=10 * i), 31500, delivery="d-new", ours=2700, harness_tokens=28700))
    await _policy(db)
    await db.flush()

    result = await why_service.why(db, "claude", "implementation", at=STEP_AT, now=NOW)  # +5% is under jump_pct: ask for the time

    assert (result.kind, result.cause) == ("at", "ours") and result.parts["ours"] == 1500 and result.parts["harness"] == 0
    changes = {b.change: b for b in result.blocks}
    assert changes["grown"].label == "Test with Haiku agents" and changes["grown"].delta == 1200
    writer = changes["grown"].writer
    assert writer is not None and (writer["writer_session"], writer["writer_kind"]) == ("aico-widget-lane", "agent")
    assert changes["added"].label == "added" and changes["added"].tokens_after == 300
    assert {b.block for b in result.blocks} == {f"b-{memory_id}", "b-added"}  # the unchanged block is not listed


async def test_without_a_step_why_compares_the_last_day_with_the_week_before(db: AsyncSession) -> None:
    for i in range(20):
        db.add(_session(i, NOW - timedelta(days=4) + timedelta(hours=i), 30000))
    for i in range(3):
        db.add(_session(100 + i, NOW - timedelta(hours=3 - i), 31000))
    await _policy(db)
    await db.flush()

    result = await why_service.why(db, "claude", "implementation", now=NOW)
    empty = await why_service.why(db, "codex", "implementation", now=NOW)

    assert result.before is not None and result.after is not None
    assert (result.kind, result.before.total, result.after.total, result.after.n) == ("recent", 30000, 31000, 3)
    assert (empty.cause, empty.delta, "no measured starts" in empty.summary) == ("none", None, True)


async def test_markers_list_revisions_of_delivered_context_versions_configs_and_placements(db: AsyncSession) -> None:
    delivered, other = str(uuid.uuid4()), str(uuid.uuid4())
    db.add(_delivery("d1", STEP_AT, [_block(delivered, 100), _block("safety-directive", 100, source_type="prompt")]))
    for memory_id in (delivered, other):
        db.add(MemoryRevision(memory_uuid=memory_id, version=1, action="create", content="x", name=f"mem {memory_id[:4]}", memory_type="reference",
                              scope="global", tier=2, pinned=False, auto_inject=False, display_order=50, status="active", content_hash="h",
                              writer_kind="agent", writer_session="aico-widget-lane", created_at=STEP_AT))
    db.add(PromptRevision(prompt_slug="safety-directive", prompt_name="Safety Directive", action="update", content="c", content_hash="h",
                          writer_kind="owner", created_at=STEP_AT))
    db.add(ContextRecord(id=str(uuid.uuid4()), kind="change", actor="api", source_keys=[], created_at=STEP_AT,
                         payload={"context": {"consumer_profile": "agent_startup"}, "before_placements": [], "after_placements": [{"x": 1}]}))
    db.add(ContextRecord(id=str(uuid.uuid4()), kind="change", actor="api", source_keys=[], created_at=STEP_AT,
                         payload={"before_placements": [], "after_placements": []}))
    db.add_all([_session(1, STEP_AT, 1000, fp="a"), _session(2, STEP_AT + timedelta(hours=1), 1000, fp="a"),
                _session(3, STEP_AT + timedelta(hours=2), 1000, fp="b", version="2.1.317")])
    await db.flush()

    found = await view_markers(db, STEP_AT - timedelta(hours=1), STEP_AT + timedelta(hours=3))

    kinds = sorted((m.kind, m.ref if m.kind != "memory" else "memory") for m in found)
    assert kinds == sorted([("memory", "memory"), ("prompt", "safety-directive"), ("harness_version", "2.1.316"), ("harness_version", "2.1.317"),
                            ("config", "a"), ("config", "b"), ("placement", next(m.ref for m in found if m.kind == "placement"))])
    memory = next(m for m in found if m.kind == "memory")
    assert (memory.ref, memory.detail["writer_session"], memory.label) == (delivered, "aico-widget-lane", f"mem {delivered[:4]}")
    config_b = next(m for m in found if m.kind == "config" and m.ref == "b")
    assert config_b.detail["from_fp"] == "a" and config_b.harness == "claude"
    assert [m.kind for m in await view_markers(db, STEP_AT, STEP_AT + timedelta(hours=3), kinds=("placement",))] == ["placement"]


async def test_the_budget_policy_is_read_from_rows_and_defaults_sit_above_todays_medians(db: AsyncSession) -> None:
    migration = _migration()
    for h, r, w, j, n in migration.BUDGETS:
        db.add(ContextBudget(harness=h, role=r, warn_tokens=w, jump_pct=j, note=n))
    for name, harness, role, repo, file, note in migration.KNOBS:
        db.add(ContextKnob(name=name, harness=harness, role=role, repo_path=repo, file_path=file, note=note))
    for i in range(6):  # today's lane medians: nothing fires on day one
        db.add(_session(i, NOW - timedelta(hours=3, minutes=i), 48400))
        db.add(_session(50 + i, NOW - timedelta(days=3, minutes=i), 48000))
    await db.flush()

    policy = await load_policy(db)

    budget = policy.budget_for("claude", "lane")
    assert budget is not None and policy.jump_pct == 25 and budget.warn_tokens == 60000
    assert [k.name for k in policy.knobs_for("claude", "implementation")] == ["lane-tools.json"] and policy.knobs_for("codex", "x") == []
    assert [s.reason for s in await cell_states(db, now=NOW, policy=policy)] == [None]


async def test_the_review_item_is_pushed_at_zero_to_n_refreshed_once_a_day_and_resolved_at_zero(
    db: AsyncSession, sent: dict[str, AsyncMock], monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _policy(db)
    counts = {"n": 0}

    async def fake_queue(_db: AsyncSession, **_: Any) -> Any:
        from tests.unit.test_context_steps_alerts import _queue

        return _queue(counts["n"]) if counts["n"] else type("Q", (), {"summary": type("S", (), {"count": 0})(), "rows": []})()

    monkeypatch.setattr(alerts, "build_queue", fake_queue)
    t0 = NOW

    async def run(minutes: int) -> str:
        done = await alerts.evaluate(db, now=t0 + timedelta(minutes=minutes))
        return done[alerts.REVIEW_KEY]

    assert await run(0) == "quiet" and sent["send"].await_count == 0  # an empty queue sends and resolves nothing
    counts["n"] = 4
    assert await run(5) == "pushed" and sent["send"].await_count == 1
    counts["n"] = 7  # the count changes: still no second card inside the day
    assert await run(10) == "quiet" and await run(600) == "quiet" and sent["send"].await_count == 1
    assert await run(23 * 60 + 10) == "refreshed" and sent["send"].await_count == 2  # once per Nightshift stale window
    assert await run(23 * 60 + 15) == "quiet"
    counts["n"] = 0
    assert await run(24 * 60) == "resolved" and sent["resolve"].await_count == 1
    assert _sent(sent["resolve"]) == alerts.REVIEW_KEY
    assert await run(24 * 60 + 5) == "quiet" and sent["resolve"].await_count == 1
    counts["n"] = 2
    assert await run(25 * 60) == "pushed" and sent["send"].await_count == 3  # a new 0 -> N pushes again
    pushed = [c.args[0] for c in sent["send"].await_args_list]
    assert {p["key"] for p in pushed} == {alerts.REVIEW_KEY} and {p["push"] for p in pushed} == {"tray"}


async def test_a_failed_send_is_retried_on_the_next_pass(db: AsyncSession, sent: dict[str, AsyncMock], monkeypatch: pytest.MonkeyPatch) -> None:
    await _policy(db)
    from tests.unit.test_context_steps_alerts import _queue

    async def fake_queue(_db: AsyncSession, **_: Any) -> Any:
        return _queue(3)

    monkeypatch.setattr(alerts, "build_queue", fake_queue)
    sent["send"].return_value = False

    assert (await alerts.evaluate(db, now=NOW))[alerts.REVIEW_KEY] == "failed"
    sent["send"].return_value = True
    assert (await alerts.evaluate(db, now=NOW + timedelta(minutes=5)))[alerts.REVIEW_KEY] == "pushed"


async def test_the_review_item_counts_the_m2_queue(db: AsyncSession, sent: dict[str, AsyncMock]) -> None:
    from app.core.request_actor import RequestWriter, bind_request_writer
    from app.services.memory.repository import MemoryRepository

    await _policy(db)
    bind_request_writer(RequestWriter(kind="agent", delivery="h" * 64, session="aico-widget-lane"))
    await MemoryRepository().create(content="only for this session", memory_type="reference", scope="global", tier=3, embedding=[0.25] * 768,
                                    name="session note", summary="session note", context_kind="policy", db=db)
    await db.flush()

    done = await alerts.evaluate(db, now=NOW)

    assert done[alerts.REVIEW_KEY] == "pushed"
    notice = _sent(sent["send"])
    assert notice["title"] == "1 context change to review" and "session note" in notice["detail"] and notice["push"] == "tray"


async def test_a_budget_item_opens_with_cause_and_knob_and_resolves_when_the_cell_is_back_under(
    db: AsyncSession, sent: dict[str, AsyncMock], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path / "aico", NOW - timedelta(hours=6))
    await _policy(db, knob_repo=repo, warn=30000)
    for i in range(8):
        db.add(_session(i, NOW - timedelta(days=4, minutes=i), 24000))
    for i in range(4):
        db.add(_session(100 + i, NOW - timedelta(hours=5, minutes=i), 31000, fp="fp-b", harness_tokens=25900))
    await db.flush()

    async def no_queue(_db: AsyncSession, **_: Any) -> Any:
        return type("Q", (), {"summary": type("S", (), {"count": 0})(), "rows": []})()

    monkeypatch.setattr(alerts, "build_queue", no_queue)
    key = alerts.budget_key("claude", "implementation")

    assert (await alerts.evaluate(db, now=NOW))[key] == "pushed"
    notice = _sent(sent["send"])
    assert notice["push"] == "tray" and notice["key"] == key
    assert "over its 30.0K budget" in notice["body"] and "Knob: lane-tools.json" in notice["body"] and "Cause: config changed" in notice["body"]
    assert (await alerts.evaluate(db, now=NOW + timedelta(minutes=5)))[key] == "quiet" and sent["send"].await_count == 1

    for i in range(4):  # the cell's newest starts are back under the level
        db.add(_session(200 + i, NOW + timedelta(hours=20, minutes=i), 21000, fp="fp-c"))
    await db.flush()
    later = NOW + timedelta(hours=21)
    assert (await alerts.evaluate(db, now=later))[key] == "resolved"
    assert _sent(sent["resolve"]) == key
    assert key not in await alerts.evaluate(db, now=later + timedelta(minutes=5)) and sent["resolve"].await_count == 1


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient]:
    from fastapi import FastAPI

    from app.api.context_observability import router
    from app.db import get_db
    from app.services.api_key_auth import require_api_key

    app = FastAPI()
    app.include_router(router)

    async def _db() -> AsyncGenerator[AsyncSession]:
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[require_api_key] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def test_the_api_serves_why_and_edits_budgets_as_rows(db: AsyncSession, client: AsyncClient, tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "aico", datetime(2026, 11, 1, 14, 53, 24, tzinfo=UTC))
    await _replay_1101(db, repo)

    response = await client.get("/context-observability/why", params={"harness": "claude", "role": "lane", "at": STEP_AT.isoformat()})
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["cause"], body["knobs"][0]["label"], body["delta"]) == ("config", "lane-tools.json", -24400)

    put = await client.put("/context-observability/budgets", json={"harness": "claude", "role": "lane", "warn_tokens": 40000})
    assert put.status_code == 200 and put.json()["warn_tokens"] == 40000
    assert (await client.put("/context-observability/budgets/jump", json={"jump_pct": 40})).json()["jump_pct"] == 40
    rows = {(r["harness"], r["role"]): r for r in (await client.get("/context-observability/budgets")).json()}
    assert rows[("claude", "lane")]["warn_tokens"] == 40000 and rows[("*", "*")]["jump_pct"] == 40
    assert (await client.request("DELETE", "/context-observability/budgets", params={"harness": "*", "role": "*"})).status_code == 409
    assert (await client.request("DELETE", "/context-observability/budgets", params={"harness": "claude", "role": "lane"})).status_code == 204
    steps = await client.get("/context-observability/steps", params={"harness": "claude", "role": "lane", "days": 3})
    assert steps.status_code == 200 and steps.json()[0]["kind"] == "config"


# ---- review fixes (M3 review): the window that tripped, commits per send, hysteresis, lane scope, baseline ----


async def _no_queue(_db: AsyncSession, **_: Any) -> Any:
    return type("Q", (), {"summary": type("S", (), {"count": 0})(), "rows": []})()


@pytest.fixture
def no_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(alerts, "build_queue", _no_queue)


def _spread(db: AsyncSession, first: int, n: int, at: datetime, total: int, step: timedelta = timedelta(minutes=10), **kw: Any) -> None:
    for i in range(n):
        db.add(_session(first + i, at + step * i, total, **kw))


async def test_a_budget_card_explains_the_last_day_not_the_newest_step_of_any_direction(
    db: AsyncSession, sent: dict[str, AsyncMock], no_queue: None, tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path / "aico", NOW - timedelta(days=22, hours=1))
    await _policy(db, knob_repo=repo, warn=30000)
    _spread(db, 0, 12, NOW - timedelta(days=28), 48000, step=timedelta(hours=8))  # three weeks ago: a drop with a knob commit
    _spread(db, 100, 30, NOW - timedelta(days=21), 24000, step=timedelta(hours=14), fp="fp-b")
    _spread(db, 200, 2, NOW - timedelta(hours=20), 31000, fp="fp-b")  # last day: three starts over the level, no step of their own
    _spread(db, 210, 1, NOW - timedelta(hours=1), 31000, fp="fp-b")
    await db.commit()

    done = await alerts.evaluate(db, now=NOW)

    key = alerts.budget_key("claude", "implementation")
    assert done[key] == "pushed"
    body = sent["send"].await_args_list[-1].args[0]["body"]
    assert "over its 30.0K budget" in body and "Knob: no knob of ours changed." in body
    assert "lane-tools.json" not in body and "-2" not in body  # the old drop (-24K, the knob) is not this card's cause
    assert "Harness +" in body


async def test_a_failure_after_a_send_cannot_make_the_next_pass_send_it_again(
    db: AsyncSession, sent: dict[str, AsyncMock], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.subscription_accounting import collector
    from tests.unit.test_context_steps_alerts import _queue

    async def queue(_db: AsyncSession, **_: Any) -> Any:
        return _queue(3)

    async def broken(*_: Any, **__: Any) -> Any:
        raise RuntimeError("db hiccup")

    monkeypatch.setattr(alerts, "build_queue", queue)
    await _policy(db)
    await db.commit()
    monkeypatch.setattr(alerts, "cell_states", broken)

    await collector._evaluate_context_alerts(db)  # review is sent, then the budget half fails and the pass rolls back
    monkeypatch.undo()
    monkeypatch.setattr(alerts, "build_queue", queue)
    monkeypatch.setattr("app.services.owner_notice.send_notice", sent["send"])
    done = await alerts.evaluate(db, now=NOW + timedelta(minutes=5))

    assert done[alerts.REVIEW_KEY] == "quiet" and sent["send"].await_count == 1


async def test_a_cell_keeps_its_item_through_thin_data_and_a_band_and_clears_only_when_clearly_under(
    db: AsyncSession, sent: dict[str, AsyncMock], no_queue: None,
) -> None:
    await _policy(db, warn=30000)
    _spread(db, 0, 8, NOW - timedelta(days=4), 24000)
    _spread(db, 100, 3, NOW - timedelta(hours=5), 31000)
    await db.commit()
    key = alerts.budget_key("claude", "implementation")

    async def at(hours: float) -> str:
        return (await alerts.evaluate(db, now=NOW + timedelta(hours=hours))).get(key, "untouched")

    assert await at(0) == "pushed" and sent["send"].await_count == 1
    assert await at(20) == "untouched" and sent["resolve"].await_count == 0  # no start in the last day: not "back under"
    _spread(db, 200, 3, NOW + timedelta(hours=21), 31000)
    await db.commit()
    assert await at(22.1) == "quiet" and sent["send"].await_count == 1  # it comes back inside the day: no second card
    _spread(db, 300, 3, NOW + timedelta(hours=48), 28000)  # 93% of the level: neither over nor clear
    await db.commit()
    assert await at(50) == "refreshed" and sent["resolve"].await_count == 0
    assert "near its budget" in sent["send"].await_args_list[-1].args[0]["title"]
    _spread(db, 400, 3, NOW + timedelta(hours=74), 26000)  # under 90%
    await db.commit()
    assert await at(75) == "resolved" and sent["resolve"].await_count == 1


async def test_one_failed_send_ends_the_pass_instead_of_costing_a_timeout_per_cell(
    db: AsyncSession, sent: dict[str, AsyncMock], no_queue: None,
) -> None:
    await _policy(db, warn=30000)
    for n, role in enumerate(("implementation", "research")):
        _spread(db, n * 100, 8, NOW - timedelta(days=4), 24000, role=role)
        _spread(db, n * 100 + 50, 3, NOW - timedelta(hours=5), 31000, role=role)
    await db.commit()
    sent["send"].return_value = False

    done = await alerts.evaluate(db, now=NOW)

    assert sent["send"].await_count == 1
    assert sorted(v for k, v in done.items() if k.startswith(alerts.BUDGET_KEY_PREFIX)) == ["deferred", "failed"]
    sent["send"].return_value = True
    again = await alerts.evaluate(db, now=NOW + timedelta(minutes=5))
    assert sorted(v for k, v in again.items() if k.startswith(alerts.BUDGET_KEY_PREFIX)) == ["pushed", "pushed"]  # nothing was stored for either


async def test_a_lane_step_is_explained_in_the_role_it_happened_in(db: AsyncSession) -> None:
    await _policy(db)
    _spread(db, 0, 12, NOW - timedelta(days=4), 20000, step=timedelta(hours=6))  # implementation
    _spread(db, 100, 6, NOW - timedelta(days=1), 30000, fp="fp-b")  # ... rises 50% with a config change
    _spread(db, 200, 14, NOW - timedelta(days=4), 20000, step=timedelta(hours=7), role="research")  # research lanes are flat
    _spread(db, 300, 24, NOW - timedelta(days=1), 20000, step=timedelta(minutes=30), role="research")

    result = await why_service.why(db, "claude", "lane", now=NOW)

    assert (result.kind, result.delta, result.after.n if result.after else None) == ("config", 10000, 6)  # the step's own delta
    assert result.before is not None and result.before.n == 12


async def test_a_knob_commit_without_a_fingerprint_change_is_a_marker_not_a_cause(db: AsyncSession, tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "aico", STEP_AT - timedelta(minutes=30))
    _spread(db, 0, 20, STEP_AT - timedelta(days=2), 40000, step=timedelta(hours=2))
    _spread(db, 100, 6, STEP_AT, 48000)
    await _policy(db, knob_repo=repo)

    result = await why_service.why(db, "claude", "implementation", at=STEP_AT, now=NOW)

    assert (result.cause, result.knobs) == ("harness", [])
    assert [m.kind for m in result.markers if m.kind == "knob"] == ["knob"]  # still on the timeline
    assert "Knob" not in result.summary


async def test_a_version_and_a_knob_at_once_are_not_told_apart(db: AsyncSession, tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "aico", STEP_AT - timedelta(minutes=30))
    _spread(db, 0, 20, STEP_AT - timedelta(days=2), 40000, step=timedelta(hours=2))
    _spread(db, 100, 6, STEP_AT, 48000, version="2.1.318", fp="fp-b")
    await _policy(db, knob_repo=repo)

    result = await why_service.why(db, "claude", "implementation", at=STEP_AT, now=NOW)

    assert result.cause == "unknown" and [k.label for k in result.knobs] == ["lane-tools.json"]


async def test_a_part_we_cannot_see_is_unknown_not_blamed_on_agent_hub(db: AsyncSession) -> None:
    await _policy(db)
    for i in range(20):
        row = _session(i, STEP_AT - timedelta(days=2) + timedelta(hours=2 * i), 30000, ours=1000)
        row.parts = {"total": {"tokens": 30000}, "ours": {"tokens": 1000}}  # no harness or brief split
        db.add(row)
    for i in range(6):
        row = _session(100 + i, STEP_AT + timedelta(minutes=10 * i), 38000, ours=1300)
        row.parts = {"total": {"tokens": 38000}, "ours": {"tokens": 1300}}
        db.add(row)
    await db.flush()

    result = await why_service.why(db, "claude", "implementation", at=STEP_AT, now=NOW)

    assert (result.cause, result.parts["ours"], result.parts["harness"]) == ("unknown", 300, None)


async def test_budget_rows_for_the_lane_group_and_the_seeded_knob_reach_lane_cells(db: AsyncSession) -> None:
    migration = _migration()
    assert [(k[0], k[1], k[2]) for k in migration.KNOBS] == [("lane-tools.json", "claude", "lane")]  # not every cell
    db.add_all([ContextBudget(harness="*", role="*", warn_tokens=60000, jump_pct=25), ContextBudget(harness="claude", role="lane", warn_tokens=40000)])
    await db.flush()
    policy = await load_policy(db)

    for cell in ("implementation", "research"):
        budget = policy.budget_for("claude", cell)
        assert budget is not None and budget.warn_tokens == 40000
    budget = policy.budget_for("claude", "coordinator")
    assert budget is not None and budget.warn_tokens == 60000


async def test_putting_a_budget_moves_updated_at(db: AsyncSession, client: AsyncClient) -> None:
    await _policy(db)
    old = datetime(2026, 1, 1, tzinfo=UTC)
    await client.put("/context-observability/budgets", json={"harness": "claude", "role": "blank", "warn_tokens": 1000})
    await db.execute(text("UPDATE context_budgets SET updated_at = :t"), {"t": old})

    put = await client.put("/context-observability/budgets", json={"harness": "claude", "role": "blank", "warn_tokens": 2000})

    assert put.status_code == 200 and datetime.fromisoformat(put.json()["updated_at"]) > old


async def test_changes_written_before_the_deploy_count_as_reviewed_and_later_agent_writes_queue(
    db: AsyncSession, sent: dict[str, AsyncMock],
) -> None:
    from app.core.request_actor import RequestWriter, bind_request_writer
    from app.services.memory.repository import MemoryRepository

    await _policy(db)
    bind_request_writer(RequestWriter(kind="agent", delivery="h" * 64, session="aico-widget-lane"))
    ids = []
    for name in ("before deploy", "after deploy"):
        memory = await MemoryRepository().create(content=f"note {name}", memory_type="reference", scope="global", tier=3, embedding=[0.25] * 768,
                                                 name=name, summary=name, context_kind="policy", db=db)
        ids.append(str(memory.id))
    deploy = NOW - timedelta(hours=1)
    for memory_id, at in zip(ids, (deploy - timedelta(days=2), deploy + timedelta(minutes=10)), strict=True):
        await db.execute(text("UPDATE memory_revisions SET created_at = :t WHERE memory_uuid = :m"), {"t": at, "m": memory_id})
    await db.execute(text("INSERT INTO subscription_usage_cursors (path, \"offset\", state) VALUES (:p, 0, CAST(:s AS json))"),
                     {"p": alerts.BASELINE_STATE, "s": json.dumps({"deploy_at": deploy.isoformat(), "done": False})})
    await db.commit()

    done = await alerts.evaluate(db, now=NOW)

    assert done["review-baseline"] == "baselined 1" and done[alerts.REVIEW_KEY] == "pushed"
    notice = sent["send"].await_args_list[-1].args[0]
    assert notice["title"] == "1 context change to review" and "after deploy" in notice["detail"] and "before deploy" not in notice["detail"]
    assert (await alerts.evaluate(db, now=NOW + timedelta(minutes=5)))["review-baseline"] == "quiet"
