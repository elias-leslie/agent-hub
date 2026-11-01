"""Pi binding, Agent Hub first calls, growth and delivery-only rows against Postgres."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.schema import CreateTable

from app.models import ContextDelivery, CostLog, Session, SessionEvent, UsageCall, UsageSession
from app.services.context_observability import agent_hub_turn, delivery_only, extra_capture, growth
from tests.api.test_sessions_listing_pg import pg_db  # noqa: F401  (fixture)

pytestmark = pytest.mark.integration

AT = datetime(2026, 11, 1, 12, tzinfo=UTC)


@pytest_asyncio.fixture
async def db(pg_db: AsyncSession) -> AsyncSession:  # noqa: F811
    conn = await pg_db.connection()
    await conn.run_sync(lambda c: c.execute(CreateTable(ContextDelivery.__table__, include_foreign_key_constraints=[])))
    return pg_db


def _delivery(delivery_id: str, *, seconds: float, project: str = "neri", role: str = "hunting", surface: str = "pi",
              host: str | None = None, session_id: str | None = None, source: str = "file", est: int = 5000) -> ContextDelivery:
    return ContextDelivery(
        delivery_id=delivery_id, generated_at=AT + timedelta(seconds=seconds), source=source, surface=surface, project_id=project,
        session_id=session_id, work_role=role, coordinator=role == "coordinator", consumer_tags=[f"work-role:{role}"], host=host,
        est_tokens=est, payload_hash=delivery_id.ljust(64, "0"), rendered_chars=est * 4, by_scope={}, blocks=[],
    )


def _raw(**over) -> dict:
    return {"harness": "pi", "sid": "pi-1", "cwd": "/srv/workspaces/projects/neri", "started": AT, "first_at": AT + timedelta(seconds=4),
            "model": "deepseek-v4.1-flash", "total": 8000, "brief_chars": 400, "core_chars": 800, "listing_chars": 4000,
            "tools_chars": 4000, "delivery_chars": 0, "sections": {}, **over}


async def test_pi_session_binds_the_nearest_delivery_of_its_project_and_lands_as_a_pi_row(db: AsyncSession, tmp_path: Path) -> None:
    db.add_all([_delivery("near-other-project", seconds=-1, project="aico", role="review"),
                _delivery("mine", seconds=-3, project="neri", role="hunting"),
                _delivery("too-far", seconds=-60, project="neri", role="coordinator")])
    await db.flush()
    path = tmp_path / "2026-11-01T12-00-00-000Z_pi-1.jsonl"
    path.write_text("")

    assert await extra_capture.apply_pi(db, [(path, _raw())], now=AT + timedelta(minutes=1), version="1.4.0") == 1
    assert await extra_capture.apply_pi(db, [(path, _raw())], now=AT + timedelta(minutes=1), version="1.4.0") == 1  # rerun

    row = (await db.execute(select(UsageSession))).scalar_one()
    assert row.parts is not None
    assert (row.provider, row.harness, row.harness_version, row.work_role, row.delivery_id) == ("pi", "pi", "1.4.0", "hunting", "mine")
    assert (row.first_turn_tokens, row.launch_mode, row.model, row.project) == (8000, "project", "deepseek-v4.1-flash", "neri")
    assert row.parts["ours"] == {"tokens": 5000, "method": "estimate"} and row.parts["version_basis"] == "first_sighting"
    assert row.peak_context_tokens is None  # Pi has no usage_calls: unknown, not zero


async def test_blank_slate_pi_session_takes_no_delivery_and_unknown_version_stays_unknown(db: AsyncSession, tmp_path: Path) -> None:
    db.add(_delivery("d", seconds=-2))
    await db.flush()
    path = tmp_path / "--home-kasadis-.local-share-aico-blank-slate-x--" / "2026-11-01T12-00-00-000Z_pi-1.jsonl"
    path.parent.mkdir()
    path.write_text("")

    await extra_capture.apply_pi(db, [(path, _raw(total=2000, core_chars=2800, listing_chars=0))], now=AT, version=None)

    row = (await db.execute(select(UsageSession))).scalar_one()
    assert row.parts is not None
    assert (row.launch_mode, row.delivery_id, row.harness_version, row.parts["ours"]["tokens"]) == ("blank", None, None, 0)
    assert row.parts["version_basis"] == "unknown"


def _call(key: str, minutes: int, ctx: int, *, model: str = "m", session: str = "s1", agent: str = "") -> UsageCall:
    return UsageCall(call_key=key, occurred_at=AT + timedelta(minutes=minutes), provider="claude", session_id=session, agent_id=agent,
                     model=model, input_tokens=100, cached_input_tokens=ctx - 150, cache_write_tokens=50, output_tokens=10)


async def test_peak_and_compactions_come_from_usage_calls_per_chain(db: AsyncSession) -> None:
    for sid in ("s1", "s2", "empty"):
        db.add(UsageSession(provider="claude", session_id=sid, agent_id="", first_at=AT, last_at=AT + timedelta(hours=1)))
    db.add_all([
        _call("a", 0, 40_000), _call("b", 1, 120_000), _call("c", 2, 25_000),  # compaction: 120K -> 25K
        _call("d", 3, 60_000), _call("e", 4, 30_000),  # 60K -> 30K is exactly half: not under the ratio
        _call("h1", 1, 2_000, model="haiku"), _call("h2", 2, 90_000, model="opus-side"),  # other models: own chains
        _call("x", 0, 50_000, session="s2"), _call("y", 1, 55_000, session="s2"),
    ])
    await db.flush()

    await growth.update_since(db, AT)

    rows = {r.session_id: r for r in (await db.execute(select(UsageSession))).scalars()}
    assert (rows["s1"].peak_context_tokens, rows["s1"].compaction_count) == (120_000, 1)
    assert (rows["s2"].peak_context_tokens, rows["s2"].compaction_count) == (55_000, 0)
    assert (rows["empty"].peak_context_tokens, rows["empty"].compaction_count) == (None, None)


async def test_growth_update_for_given_sessions_only_touches_them(db: AsyncSession) -> None:
    for sid in ("s1", "s2"):
        db.add(UsageSession(provider="claude", session_id=sid, agent_id="", first_at=AT, last_at=AT))
    db.add_all([_call("a", 0, 40_000), _call("x", 0, 50_000, session="s2")])
    await db.flush()

    assert await growth.update_sessions(db, [("claude", "s1")]) == 1

    rows = {r.session_id: r.peak_context_tokens for r in (await db.execute(select(UsageSession))).scalars()}
    assert rows == {"s1": 40_000, "s2": None}
    assert await growth.update_sessions(db, []) == 0


async def test_agent_hub_first_call_skips_native_counted_rows_and_reads_the_brief(db: AsyncSession) -> None:
    from app.models.session import NATIVE_COUNTED_NOTE

    for sid, slug in (("c1", "critic"), ("w1", "coder")):
        db.add(Session(id=sid, project_id="summitflow", provider="claude", model="m", agent_slug=slug, request_source="summitflow",
                       created_at=AT, updated_at=AT))
    await db.flush()
    db.add_all([
        CostLog(session_id="c1", model="m", input_tokens=300, cache_read_tokens=5000, cache_write_tokens=200, output_tokens=5, created_at=AT),
        CostLog(session_id="c1", model="m", input_tokens=900, cache_read_tokens=5000, output_tokens=5, created_at=AT + timedelta(seconds=9)),
        CostLog(session_id="w1", model="m", input_tokens=9000, output_tokens=5, created_at=AT, cost_note=NATIVE_COUNTED_NOTE),
        SessionEvent(session_id="c1", turn=1, sequence=1, event_type="user_message", content="b" * 1200),
    ])
    await db.flush()

    calls = await agent_hub_turn.first_calls(db, since=AT - timedelta(days=1))

    assert [(c["session_id"], c["input_tokens"], c["brief_chars"], c["agent_slug"]) for c in calls] == [("c1", 300, 1200, "critic")]


async def test_agent_hub_capture_binds_the_session_delivery_and_is_idempotent(db: AsyncSession) -> None:
    db.add(Session(id="c1", project_id="summitflow", provider="claude", model="m", agent_slug="critic", request_source="summitflow",
                   created_at=AT, updated_at=AT))
    await db.flush()
    db.add_all([
        CostLog(session_id="c1", model="m", input_tokens=300, cache_read_tokens=6500, cache_write_tokens=200, output_tokens=5, created_at=AT),
        SessionEvent(session_id="c1", turn=1, sequence=1, event_type="user_message", content="b" * 400),
        _delivery("ad", seconds=-5, surface="agent_runtime", session_id="c1", source="agent", est=5000),
    ])
    await db.flush()

    async def stack(_db, _slug):
        return "s" * 400

    with patch.object(agent_hub_turn, "stack_text", stack):
        for _ in range(2):
            result = await extra_capture.capture_agent_hub(db, since=AT - timedelta(hours=1), until=None, now=AT + timedelta(minutes=2), skip_done=False)
    assert result == {"agent_hub_read": 1, "agent_hub_updated": 1}

    row = (await db.execute(select(UsageSession).where(UsageSession.provider == "agent_hub"))).scalar_one()
    assert row.parts is not None
    assert (row.launch_mode, row.first_turn_tokens, row.delivery_id, row.harness) == ("agent:critic", 7000, "ad", "agent_hub")
    assert row.parts["ours"]["tokens"] == 5100 and row.parts["harness"]["tokens"] == 1800 and row.parts["stack_basis"] == "live"
    assert row.config_fp is not None and row.work_role is None


async def test_remote_host_and_antigravity_deliveries_show_with_unknown_total_unless_a_session_carries_them(db: AsyncSession) -> None:
    db.add_all([
        _delivery("remote", seconds=0, surface="claude_code", host="neri-hunters", role="hunting"),
        _delivery("remote-measured", seconds=1, surface="codex", host="agent-work"),
        _delivery("anti", seconds=2, surface="antigravity", role="other"),
        _delivery("local", seconds=3, surface="claude_code"),
    ])
    db.add(UsageSession(provider="codex", session_id="r", agent_id="", first_at=AT, last_at=AT, delivery_id="remote-measured"))
    await db.flush()

    rows = await delivery_only.delivery_only_rows(db, since=AT - timedelta(hours=1))

    assert [(r.delivery_id, r.harness, r.host, r.total, r.harness_tokens, r.ours_tokens) for r in rows] == [
        ("remote", "claude", "neri-hunters", None, None, 5000), ("anti", "antigravity", None, None, None, 5000),
    ]
    assert "remote host" in rows[0].reason and "no readable transcript" in rows[1].reason

