"""Pi binding, Agent Hub first calls, growth and delivery-only rows against Postgres."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.schema import CreateTable

from app.models import (
    ContextDelivery,
    CostLog,
    Session,
    SessionEvent,
    SubscriptionUsageCursor,
    UsageCall,
    UsageSession,
)
from app.services.context_observability import agent_hub_turn, delivery_only, extra_capture, growth
from tests.api.test_sessions_listing_pg import pg_db  # noqa: F401  (fixture)

pytestmark = pytest.mark.integration

AT = datetime(2026, 11, 1, 12, tzinfo=UTC)


@pytest_asyncio.fixture
async def db(pg_db: AsyncSession) -> AsyncSession:  # noqa: F811
    conn = await pg_db.connection()
    for table in (ContextDelivery.__table__, SubscriptionUsageCursor.__table__):
        await conn.run_sync(lambda c, t=table: c.execute(CreateTable(t, include_foreign_key_constraints=[])))
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


async def test_remote_host_and_unreadable_harness_deliveries_show_with_unknown_total_unless_a_session_carries_them(db: AsyncSession) -> None:
    db.add_all([
        _delivery("remote", seconds=0, surface="claude_code", host="neri-hunters", role="hunting"),
        _delivery("remote-measured", seconds=1, surface="codex", host="agent-work"),
        _delivery("anti", seconds=2, surface="antigravity", role="other"),
        _delivery("local", seconds=3, surface="claude_code"),
        _delivery("open", seconds=4, surface="opencode", role="hunting"),
        _delivery("own-agent", seconds=5, surface="agent_runtime", source="agent"),  # measured from cost_logs, not delivery-only
    ])
    db.add(UsageSession(provider="codex", session_id="r", agent_id="", first_at=AT, last_at=AT, delivery_id="remote-measured"))
    await db.flush()

    rows = await delivery_only.delivery_only_rows(db, since=AT - timedelta(hours=1))

    assert [(r.delivery_id, r.harness, r.host, r.total, r.harness_tokens, r.ours_tokens) for r in rows] == [
        ("remote", "claude", "neri-hunters", None, None, 5000), ("anti", "antigravity", None, None, None, 5000),
        ("open", "opencode", None, None, None, 5000),
    ]
    assert "remote host" in rows[0].reason and "no readable transcript" in rows[1].reason and "opencode" in rows[2].reason



# ------------------------------------------------------------------ review fixes (M1b review)


async def test_agent_hub_first_call_leaves_out_whole_attempt_rows_and_other_services_calls(db: AsyncSession) -> None:
    from app.models.session import NATIVE_COUNTED_NOTE

    notes = {
        "plain": None, "native": NATIVE_COUNTED_NOTE, "native-unknown": f"{NATIVE_COUNTED_NOTE}; cost unknown",
        "via-pi": "workflow attempt via pi", "via-pi-est": "workflow attempt via pi; catalog estimate",
        "ingested": "ingested from nightshift.planner",
    }
    for sid in notes:
        db.add(Session(id=sid, project_id="summitflow", provider="claude", model="m", agent_slug="critic", request_source="summitflow",
                       created_at=AT, updated_at=AT))
    await db.flush()
    db.add_all([CostLog(session_id=sid, model="m", input_tokens=900, cache_read_tokens=5000, output_tokens=5, created_at=AT, cost_note=note)
                for sid, note in notes.items()])
    await db.flush()

    calls = await agent_hub_turn.first_calls(db, since=AT - timedelta(days=1))

    assert [c["session_id"] for c in calls] == ["plain"]


async def _snapshot(db: AsyncSession) -> dict:
    stmt = select(UsageSession).execution_options(populate_existing=True)
    return {r.provider: copy.deepcopy((r.harness_version, r.config_fp, r.parts, r.delivery_id)) for r in (await db.execute(stmt)).scalars()}


async def test_a_rerun_keeps_the_version_prompt_stack_and_parts_a_row_already_holds(db: AsyncSession, tmp_path: Path) -> None:
    path = tmp_path / "2026-11-01T12-00-00-000Z_pi-1.jsonl"
    path.write_text("")
    await extra_capture.apply_pi(db, [(path, _raw())], now=AT + timedelta(minutes=1), version="1.4.0")  # live sighting
    db.add(Session(id="c1", project_id="summitflow", provider="claude", model="m", agent_slug="critic", request_source="summitflow",
                   created_at=AT, updated_at=AT))
    await db.flush()
    db.add_all([CostLog(session_id="c1", model="m", input_tokens=300, cache_read_tokens=6500, output_tokens=5, created_at=AT)])
    await db.flush()
    stacks = iter(["a" * 400, "b" * 800])

    async def stack(_db, _slug):
        return next(stacks)

    with patch.object(agent_hub_turn, "stack_text", stack):
        await extra_capture.capture_agent_hub(db, since=AT - timedelta(hours=1), until=None, now=AT + timedelta(minutes=2), skip_done=False)
        before = await _snapshot(db)
        # a rerun days later: a newer Pi, another prompt stack, a later "now"
        later = AT + timedelta(days=3)
        await extra_capture.apply_pi(db, [(path, _raw())], now=later, version="1.9.9")
        await extra_capture.capture_agent_hub(db, since=AT - timedelta(hours=1), until=None, now=later, skip_done=False)
    after = await _snapshot(db)
    assert before["pi"][0] == "1.4.0" and before["agent_hub"][1] is not None
    assert after == before


async def test_a_backfilled_pi_row_has_no_harness_version_only_the_installed_one_in_parts(db: AsyncSession, tmp_path: Path) -> None:
    path = tmp_path / "2026-11-01T12-00-00-000Z_pi-1.jsonl"
    path.write_text("")

    await extra_capture.apply_pi(db, [(path, _raw())], now=AT + timedelta(days=3), version="1.9.9")

    row = (await db.execute(select(UsageSession))).scalar_one()
    assert row.parts is not None
    assert row.harness_version is None
    assert (row.parts["version_basis"], row.parts["installed_version"]) == ("installed_at_backfill", "1.9.9")


def _pi(tmp_path: Path, sid: str, started_s: float, *, project: str = "neri", **over) -> tuple[Path, dict]:
    path = tmp_path / f"2026-11-01T12-00-00-000Z_{sid}.jsonl"
    path.write_text("")
    started = AT + timedelta(seconds=started_s)
    return path, _raw(sid=sid, cwd=f"/srv/workspaces/projects/{project}", started=started, first_at=started + timedelta(seconds=4), **over)


async def test_pi_binds_only_within_three_before_and_eight_after_the_session_record(db: AsyncSession, tmp_path: Path) -> None:
    db.add_all([_delivery("early", seconds=-4), _delivery("edge-before", seconds=-2.5, role="review"), _delivery("edge-after", seconds=7.5, role="other"),
                _delivery("late", seconds=9)])
    await db.flush()
    heads = [_pi(tmp_path, "s-lo", 0), _pi(tmp_path, "s-hi", 100)]
    # same deliveries, session records shifted so each sees one edge delivery only
    db.add_all([_delivery("hi-late", seconds=108.5, project="aico"), _delivery("hi-in", seconds=107.5, project="aico", role="coordinator")])
    await db.flush()

    assigned = await extra_capture.assign_pi_deliveries(db, heads)

    assert assigned["s-lo"]["delivery_id"] == "edge-before"  # -2.5 s, the closest in window; -4 s and +9 s are outside
    assert assigned["s-hi"]["delivery_id"] == "hi-in"


async def test_a_delivery_serves_one_pi_session_and_the_project_match_wins(db: AsyncSession, tmp_path: Path) -> None:
    db.add_all([_delivery("only", seconds=3, project="neri", role="hunting"), _delivery("other", seconds=6, project="aico", role="review")])
    await db.flush()
    heads = [_pi(tmp_path, "a", 0, project="aico"), _pi(tmp_path, "b", 1, project="neri")]

    assigned = await extra_capture.assign_pi_deliveries(db, heads)

    # both sessions are within reach of both deliveries; each takes its own project's, none is shared
    assert {k: v["delivery_id"] for k, v in assigned.items()} == {"a": "other", "b": "only"}


async def test_three_sessions_two_deliveries_leave_one_session_without(db: AsyncSession, tmp_path: Path) -> None:
    db.add_all([_delivery("d1", seconds=2), _delivery("d2", seconds=9)])
    await db.flush()

    assigned = await extra_capture.assign_pi_deliveries(db, [_pi(tmp_path, f"s{i}", i * 2) for i in range(3)])

    assert len(assigned) == 2 and len({v["delivery_id"] for v in assigned.values()}) == 2


async def test_remote_deliveries_and_ones_too_big_for_the_first_turn_are_not_bound(db: AsyncSession, tmp_path: Path) -> None:
    db.add_all([_delivery("remote", seconds=1, host="neri-hunters"), _delivery("huge", seconds=2, est=9000)])  # total 8000
    await db.flush()

    assert await extra_capture.assign_pi_deliveries(db, [_pi(tmp_path, "s", 0)]) == {}


async def test_deliveries_held_by_an_earlier_pi_row_are_not_given_again(db: AsyncSession, tmp_path: Path) -> None:
    db.add(_delivery("d1", seconds=2))
    await db.flush()
    first = _pi(tmp_path, "first", 0)
    await extra_capture.apply_pi(db, [first], now=AT + timedelta(minutes=1), version="1.4.0")

    assigned = await extra_capture.assign_pi_deliveries(db, [first, _pi(tmp_path, "second", 1)])

    assert assigned == {}  # first keeps d1 (it is not re-matched), and d1 is taken for second


async def test_a_collector_outage_longer_than_the_lookback_is_caught_up_from_the_watermark(db: AsyncSession) -> None:
    now = AT + timedelta(days=1)
    db.add(Session(id="c1", project_id="summitflow", provider="claude", model="m", agent_slug=None, request_source="summitflow",
                   created_at=AT, updated_at=AT))
    await db.flush()
    db.add(CostLog(session_id="c1", model="m", input_tokens=300, cache_read_tokens=6500, output_tokens=5, created_at=now - timedelta(hours=9)))
    await db.flush()

    await extra_capture._store_watermark(db, now - timedelta(hours=10))  # last pass before the outage
    result = await extra_capture.capture_pass(db, touched=[], now=now)  # the row is 9 h old: beyond the 2 h lookback, after the watermark

    assert result["agent_hub_updated"] == 1
    assert (await db.execute(select(UsageSession.session_id).where(UsageSession.provider == "agent_hub"))).scalar_one() == "c1"
    marks = (await db.execute(select(SubscriptionUsageCursor.state).where(SubscriptionUsageCursor.path == "@context_extra"))).scalar_one()
    assert marks is not None and datetime.fromisoformat(marks["until"]) == now


async def test_one_agent_hub_row_that_fails_does_not_stop_the_others_or_the_transaction(db: AsyncSession) -> None:
    for sid, slug in (("bad", "broken"), ("good", "fine")):
        db.add(Session(id=sid, project_id="summitflow", provider="claude", model="m", agent_slug=slug, request_source="summitflow",
                       created_at=AT, updated_at=AT))
    await db.flush()
    db.add_all([CostLog(session_id=sid, model="m", input_tokens=300, cache_read_tokens=6500, output_tokens=5, created_at=AT + timedelta(seconds=i))
                for i, sid in enumerate(("bad", "good"))])
    await db.flush()

    async def stack(_db, slug):
        if slug == "broken":
            raise RuntimeError("stack will not render")
        return "s" * 400

    with patch.object(agent_hub_turn, "stack_text", stack):
        result = await extra_capture.capture_agent_hub(db, since=AT - timedelta(hours=1), until=None, now=AT + timedelta(minutes=2), skip_done=False)

    assert result == {"agent_hub_read": 2, "agent_hub_updated": 1}
    assert (await db.execute(select(UsageSession.session_id).where(UsageSession.provider == "agent_hub"))).scalars().all() == ["good"]


async def test_a_failing_stage_costs_only_that_stage(db: AsyncSession) -> None:
    db.add(UsageSession(provider="claude", session_id="s1", agent_id="", first_at=AT, last_at=AT))
    db.add(_call("a", 0, 40_000))
    await db.flush()

    async def boom(*_a, **_k):
        raise RuntimeError("pi unreadable")

    with patch.object(extra_capture, "capture_pi", boom):
        result = await extra_capture.capture_pass(db, touched=[("claude", "s1")], now=AT + timedelta(hours=1))

    assert result["growth_updated"] == 1
    assert (await db.execute(select(UsageSession.peak_context_tokens))).scalar_one() == 40_000
