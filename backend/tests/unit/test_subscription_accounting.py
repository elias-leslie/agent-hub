"""Subscription accounting: rates, log collection, credit draw, windows, amortization, lot draw-down."""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import make_url, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import CreateTable

from app.models import (
    SubscriptionUsageCursor,
    SubscriptionUsageDaily,
    SubscriptionUsageSnapshot,
    UsageCall,
    UsageSession,
)
from app.services.subscription_accounting import collector, rates
from app.services.subscription_accounting.summary import amortize, draw_down
from app.services.token_counter import estimate_cost


def test_codex_credit_rates_equal_api_parity() -> None:
    credits = rates.codex_credits("gpt-6.1-sol", input_tokens=1_000_000, cached_input_tokens=1_000_000, output_tokens=1_000_000)
    assert credits is not None
    assert credits == pytest.approx(50 + 2.5 + 250)
    assert credits * rates.CREDIT_API_PARITY_USD == pytest.approx(2 + 0.10 + 10)
    assert rates.codex_credits("codex/gpt-daybreak-blue-latest", input_tokens=1_000_000, cached_input_tokens=0,
                               output_tokens=0) == pytest.approx(100)
    fast = rates.codex_credits("gpt-6-luna", input_tokens=1_000_000, cached_input_tokens=0, output_tokens=0, speed="fast")
    ultra = rates.codex_credits("gpt-6-luna", input_tokens=1_000_000, cached_input_tokens=0, output_tokens=0, speed="ultrafast")
    assert (fast, ultra) == (pytest.approx(5.0), pytest.approx(15.0))
    assert rates.codex_rate("gpt-5.6-terra") is None


def test_claude_uses_one_hour_cache_write_rate_and_modifiers() -> None:
    usd = rates.claude_api_equiv_usd("claude-opus-5-5", input_tokens=0, output_tokens=0, cache_write_1h=1_000_000)
    assert usd == pytest.approx(8.0)
    fast = rates.claude_api_equiv_usd("claude-opus-5-5", input_tokens=1_000_000, output_tokens=0, speed="fast", geo="us")
    assert fast == pytest.approx(4.0 * 2 * 1.1)
    long = rates.claude_api_equiv_usd("claude-haiku-5-5", input_tokens=200_000, output_tokens=0)
    assert long == pytest.approx(0.2 * 0.10 * 5)


def test_subscription_calls_cost_zero_cash_but_keep_api_equivalent() -> None:
    sub = estimate_cost(1_000_000, 0, "codex/gpt-6.1-sol")
    assert sub.total_cost_usd == 0.0
    assert sub.billing_mode == "subscription"
    assert sub.api_equiv_usd == pytest.approx(2.0)
    assert estimate_cost(1_000_000, 0, "claude-sonnet-5-5").api_equiv_usd == pytest.approx(2.0)
    metered = estimate_cost(1_000_000, 0, "gemini-3.5-flash")
    assert metered.billing_mode == "metered" and metered.total_cost_usd > 0


def _jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _token_count(ts: str, total: int, inp: int, cached: int, out: int, used: float, balance: str) -> dict:
    return {
        "timestamp": ts,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {"total_tokens": total},
                "last_token_usage": {"input_tokens": inp, "cached_input_tokens": cached, "output_tokens": out},
            },
            "rate_limits": {
                "primary": {"used_percent": used, "window_minutes": 10080, "resets_at": 1792297711},
                "credits": {"has_credits": True, "unlimited": False, "balance": balance},
                "plan_type": "plus",
            },
        },
    }


def _native_codex(response: str, inp: int, cached: int, out: int, ordinal: int = 2) -> dict:
    return {"timestamp": "2026-10-11T12:00:02Z", "type": "token_usage_record", "ordinal": ordinal,
            "payload": {"thread_id": "thread", "response_id": response,
                        "usage": {"input_tokens": inp, "cached_input_tokens": cached, "output_tokens": out}}}


def test_native_codex_pairs_legacy_usage_and_keeps_compaction_once(tmp_path: Path) -> None:
    path = tmp_path / "rollout.jsonl"
    pair = _token_count("2026-10-11T12:00:03Z", 1100, 1000, 400, 100, 0, "100")
    reset = _token_count("2026-10-11T12:00:05Z", 1100, 0, 0, 0, 0, "100")
    _jsonl(path, [
        {"type": "session_meta", "payload": {"id": "thread", "cwd": "/srv/workspaces/projects/agent-hub"}},
        {"type": "turn_context", "payload": {"model": "gpt-6.1-sol"}},
        _native_codex("ordinary", 1000, 400, 100), pair,
        _native_codex("compact", 2000, 1500, 50, 4),
        {"type": "compacted", "payload": {"compaction_response_id": "compact"}}, reset,
        {"type": "turn_context", "payload": {"model": "gpt-6-luna"}},
        _native_codex("next", 100, 20, 10, 8),
        _token_count("2026-10-11T12:00:06Z", 1210, 100, 20, 10, 0, "100"),
    ])
    result = collector.PassResult()
    state: dict = {}
    offset = collector._codex_file(path, 0, state, result)
    assert len(result.calls) == 3
    assert [c.key for c in result.calls] == ["codex:thread:1100", "codex:thread:compact", "codex:thread:1210"]
    assert sum(c.input_tokens + c.cached_input_tokens for c in result.calls) == 3100
    assert sum(c.output_tokens for c in result.calls) == 160
    assert result.calls[-1].model == "gpt-6-luna"
    assert sum(r.requests for r in result.rollups.values()) == 3
    _jsonl(path, [_native_codex("next", 100, 20, 10, 10),
                  _token_count("2026-10-11T12:00:07Z", 1210, 100, 20, 10, 0, "100")])
    retry = collector.PassResult()
    collector._codex_file(path, offset, state, retry)
    assert retry.calls == [] and not retry.rollups


def test_native_codex_child_excludes_inherited_usage(tmp_path: Path) -> None:
    path = tmp_path / "rollout.jsonl"
    _jsonl(path, [
        {"type": "session_meta", "payload": {"id": "thread", "session_id": "parent",
                                               "subagent_history_start_ordinal": 10}},
        {"type": "turn_context", "payload": {"model": "gpt-6.1-sol"}},
        _native_codex("parent-response", 1000, 400, 100, 2),
        _native_codex("child-response", 100, 20, 10, 11),
        {"type": "compacted", "payload": {"compaction_response_id": "child-response"}},
    ])
    result = collector.PassResult()
    collector._codex_file(path, 0, {}, result)
    assert [(c.session_id, c.agent_id, c.input_tokens) for c in result.calls] == [("parent", "thread", 80)]


def _claude_usage(out: int) -> dict:
    return {"timestamp": "2026-10-11T12:00:00Z", "requestId": "request", "cwd": "/srv/workspaces/projects/agent-hub",
            "message": {"id": "message", "model": "claude-opus-5-5",
                        "usage": {"input_tokens": 10, "output_tokens": out, "cache_read_input_tokens": 400}}}


@pytest.mark.parametrize("split", [False, True])
def test_claude_stream_final_usage_replaces_initial_usage(tmp_path: Path, split: bool) -> None:
    path = tmp_path / "claude.jsonl"
    _jsonl(path, [_claude_usage(21)])
    state: dict = {}
    first = collector.PassResult()
    if not split:
        _jsonl(path, [_claude_usage(191)])
    offset = collector._claude_file(path, 0, state, first)
    if split:
        _jsonl(path, [_claude_usage(191)])
        final = collector.PassResult()
        offset = collector._claude_file(path, offset, state, final)
    else:
        final = first
    assert len(final.calls) == 1 and final.calls[0].output_tokens == 191
    assert sum(r.requests for r in first.rollups.values()) == 1
    assert sum(r.output_tokens for r in first.rollups.values()) + (
        sum(r.output_tokens for r in final.rollups.values()) if split else 0) == 191
    _jsonl(path, [_claude_usage(191), _claude_usage(21)])  # a stale streamed retry must not replace final usage
    retry = collector.PassResult()
    collector._claude_file(path, offset, state, retry)
    assert retry.calls == [] and not retry.rollups


def test_codex_pending_native_usage_survives_partial_legacy_tail(tmp_path: Path) -> None:
    path = tmp_path / "rollout.jsonl"
    _jsonl(path, [{"type": "turn_context", "payload": {"model": "gpt-6.1-sol"}},
                  _native_codex("ordinary", 1000, 400, 100)])
    legacy = json.dumps(_token_count("2026-10-11T12:00:03Z", 1100, 1000, 400, 100, 0, "100"))
    with path.open("a") as fh:
        fh.write(legacy[:40])
    state: dict = {}
    first = collector.PassResult()
    offset = collector._codex_file(path, 0, state, first)
    assert first.calls == [] and "pending_usage" in state
    with path.open("a") as fh:
        fh.write(legacy[40:] + "\n")
    final = collector.PassResult()
    collector._codex_file(path, offset, state, final)
    assert len(final.calls) == 1 and final.calls[0].output_tokens == 100
    assert "pending_usage" not in state


def test_named_usage_replay_resumes_its_byte_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_HUB_CODEX_SESSIONS", str(tmp_path / "codex"))
    monkeypatch.setenv("AGENT_HUB_CLAUDE_PROJECTS", str(tmp_path / "claude"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    for name in ("a", "b"):
        _jsonl(tmp_path / "claude" / "p" / f"{name}.jsonl", [_claude_usage(191)])
    first = collector.scan({})
    cursors = dict(first.cursors)
    replay = collector.scan(cursors, byte_budget=1, replay="native-usage-test")
    assert replay.replay_pending == 1 and len(replay.calls) == 1 and replay.reconcile
    cursors.update(replay.cursors)
    resumed = collector.scan(cursors, byte_budget=1, replay="native-usage-test")
    assert resumed.replay_pending == 0 and len(resumed.calls) == 1
    cursors.update(resumed.cursors)
    assert collector.scan(cursors, replay="native-usage-test").calls == []


@pytest.mark.parametrize("replay", [None, "native-usage-20261022"])
def test_usage_collect_cli_parses_optional_replay(replay: str | None, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from app.cli import usage_collect

    run = AsyncMock(return_value={"replay_pending": 0})
    monkeypatch.setattr(usage_collect, "run", run)
    monkeypatch.setattr("sys.argv", ["usage_collect", *(["--replay", replay] if replay else [])])
    usage_collect.main()
    run.assert_awaited_once_with(replay=replay)
    assert json.loads(capsys.readouterr().out) == {"replay_pending": 0}


@pytest.mark.parametrize("prune", [False, True])
async def test_usage_replay_can_skip_existing_retention_pruning(prune: bool) -> None:
    db = SimpleNamespace(execute=AsyncMock())
    await collector._persist(db, collector.PassResult(), [], [], prune=prune)
    assert db.execute.await_count == (3 if prune else 0)


async def test_usage_collect_replay_uses_initialized_collector(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.cli import usage_collect

    db = object()
    calls = []

    @asynccontextmanager
    async def session():
        yield db

    async def refresh(actual_db):
        assert actual_db is db
        calls.append("catalog")

    async def collect(actual_db, **kwargs):
        assert actual_db is db and kwargs == {"min_interval_s": 0, "replay": "native-usage-test"}
        calls.append("collect")
        return {"replay_pending": 0}

    monkeypatch.setattr(usage_collect, "async_session", session)
    monkeypatch.setattr(usage_collect, "refresh_runtime_model_catalog", refresh)
    monkeypatch.setattr(usage_collect, "collect", collect)
    assert await usage_collect.run(replay="native-usage-test") == {"replay_pending": 0}
    assert calls == ["catalog", "collect"]


@pytest.mark.integration
@pytest.mark.parametrize("previously_unpriced", [False, True])
async def test_native_usage_reconciliation_updates_ledger_and_daily_totals_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, previously_unpriced: bool,
) -> None:
    configured = os.environ.get("TEST_AGENT_HUB_DB_URL")
    if not configured:
        pytest.skip("TEST_AGENT_HUB_DB_URL is required")
    url = make_url(configured).set(drivername="postgresql+asyncpg")
    assert url.database and url.database.endswith("_test")
    monkeypatch.setenv("AGENT_HUB_CODEX_SESSIONS", str(tmp_path / "codex"))
    monkeypatch.setenv("AGENT_HUB_CLAUDE_PROJECTS", str(tmp_path / "claude"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    codex = tmp_path / "codex" / "2026" / "10" / "11" / "rollout.jsonl"
    claude = tmp_path / "claude" / "p" / "s.jsonl"
    _jsonl(codex, [
        {"type": "session_meta", "payload": {"id": "thread", "cwd": "/srv/workspaces/projects/agent-hub"}},
        {"type": "turn_context", "payload": {"model": "gpt-6.1-sol"}},
        _native_codex("ordinary", 1000, 400, 100),
        _token_count("2026-10-11T12:00:03Z", 1100, 1000, 400, 100, 0, "100"),
        _native_codex("compact", 2000, 1500, 50, 4),
        {"type": "compacted", "payload": {"compaction_response_id": "compact"}},
        _token_count("2026-10-11T12:00:05Z", 1100, 0, 0, 0, 0, "100"),
    ])
    _jsonl(claude, [_claude_usage(21), _claude_usage(191)])
    full = collector.scan({})
    initial = collector.PassResult(sessions=full.sessions)
    for call in full.calls:
        if call.key == "codex:thread:compact":
            continue
        if call.provider == "claude":
            call = replace(call, output_tokens=21, api_equiv_usd=None if previously_unpriced else 0.00054)
        initial.calls.append(call)
    engine = create_async_engine(url)
    schema = f"native_usage_{uuid4().hex}"
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(text(f"CREATE SCHEMA {schema}"))
            await connection.execute(text(f"SET LOCAL search_path TO {schema}"))
            for model in (UsageCall, UsageSession, SubscriptionUsageDaily, SubscriptionUsageCursor, SubscriptionUsageSnapshot):
                await connection.execute(CreateTable(model.__table__))
            async with AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as db:
                await collector._persist(db, initial, [], [])
                # Same committed source offsets as the buggy collector: replay needs to discover the
                # missing compaction and replace the already-priced initial Claude response.
                replay = collector.scan(full.cursors, replay="native-usage-test")
                await collector._persist(db, replay, [], [])
                await db.flush()
                calls = (await db.execute(select(UsageCall).execution_options(populate_existing=True))).scalars().all()
                rolls = (await db.execute(select(SubscriptionUsageDaily).execution_options(populate_existing=True))).scalars().all()
                assert len(calls) == 3
                assert sum(c.output_tokens for c in calls) == 341
                assert sum(r.requests for r in rolls) == 3
                assert sum(r.input_tokens for r in rolls) == 1110
                assert sum(r.cached_input_tokens for r in rolls) == 2300
                assert sum(r.output_tokens for r in rolls) == 341
                assert sum(r.unpriced_tokens for r in rolls) == 0
                expected_usd = sum(c.api_equiv_usd or 0 for c in full.calls)
                assert sum(r.api_equiv_usd for r in rolls) == pytest.approx(expected_usd)
                # A new explicit replay and a retried persistence must each be no-ops.
                again = collector.scan(replay.cursors, replay="native-usage-test-again")
                await collector._persist(db, again, [], [])
                await collector._persist(db, again, [], [])
                rolls = (await db.execute(select(SubscriptionUsageDaily).execution_options(populate_existing=True))).scalars().all()
                assert sum(r.requests for r in rolls) == 3
                assert sum(r.output_tokens for r in rolls) == 341
                assert sum(r.api_equiv_usd for r in rolls) == pytest.approx(expected_usd)
            await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def _isolated_homes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No test reads the real owner or agent home."""
    monkeypatch.setenv("AGENT_HUB_NATIVE_HOMES", str(tmp_path / "nohome"))


def test_scan_reads_codex_and_claude_incrementally(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    codex = tmp_path / "codex"
    claude = tmp_path / "claude"
    monkeypatch.setenv("AGENT_HUB_CODEX_SESSIONS", str(codex))
    monkeypatch.setenv("AGENT_HUB_CLAUDE_PROJECTS", str(claude))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    session = codex / "2026" / "10" / "11" / "rollout.jsonl"
    _jsonl(session, [
        {"timestamp": "2026-10-11T12:00:00Z", "type": "session_meta",
         "payload": {"cwd": "/srv/workspaces/projects/agent-hub"}},
        {"timestamp": "2026-10-11T12:00:01Z", "type": "turn_context", "payload": {"model": "gpt-6.1-sol"}},
        _token_count("2026-10-11T12:00:02Z", 1100, 1000, 400, 100, 100.0, "1000.0"),
        _token_count("2026-10-11T12:00:03Z", 1100, 1000, 400, 100, 100.0, "990.0"),  # same total: no double count
    ])
    _jsonl(claude / "-srv-x" / "s.jsonl", [
        {"timestamp": "2026-10-11T12:00:00Z", "requestId": "r1", "cwd": "/srv/workspaces/projects/nightshift",
         "message": {"id": "m1", "model": "claude-opus-5-5", "usage": {
             "input_tokens": 10, "output_tokens": 1000, "cache_read_input_tokens": 0,
             "cache_creation_input_tokens": 1_000_000,
             "cache_creation": {"ephemeral_1h_input_tokens": 1_000_000, "ephemeral_5m_input_tokens": 0}}}},
    ] * 2)  # streamed duplicate of the same message
    now = datetime(2026, 10, 11, 13, tzinfo=UTC).timestamp()

    first = collector.scan({}, now=now)
    rolls = {k[1]: (k, v) for k, v in first.rollups.items()}
    key, codex_roll = rolls["codex"]
    assert key[2:4] == ("gpt-6.1-sol", "agent-hub")
    assert (codex_roll.requests, codex_roll.input_tokens, codex_roll.cached_input_tokens) == (1, 600, 400)
    assert codex_roll.api_equiv_usd == pytest.approx((600 * 50 + 400 * 2.5 + 100 * 250) / 1e6 * 0.04)
    key, claude_roll = rolls["claude"]
    assert key[3] == "nightshift" and claude_roll.requests == 1
    assert claude_roll.api_equiv_usd == pytest.approx((10 * 4 + 1_000_000 * 8 + 1000 * 20) / 1e6)
    assert [b.balance for b in first.balances] == [1000.0, 990.0]

    cursors = dict(first.cursors)
    assert collector.scan(cursors, now=now).rollups == {}
    _jsonl(session, [_token_count("2026-10-11T12:05:00Z", 1300, 150, 0, 50, 100.0, "980.0")])
    again = collector.scan(cursors, now=now)
    (_, roll), = again.rollups.items()
    assert roll.requests == 1 and roll.input_tokens == 150


def test_credit_draws_ignore_stale_reports_and_detect_new_lots() -> None:
    t0 = datetime(2026, 9, 30, 10, tzinfo=UTC)

    def ev(minutes: int, balance: float) -> collector.BalanceEvent:
        return collector.BalanceEvent(t0 + timedelta(minutes=minutes), balance, "gpt-6.1-sol", "agent-hub", "standard")

    result = collector.PassResult()
    state: dict = {}
    grant_at = t0 + timedelta(minutes=1)
    events = [ev(0, 0.0), ev(1, 62500.0), ev(2, 62400.0), ev(3, 62480.0), ev(4, 62300.0), ev(600, 70000.0)]
    new_lots = collector.apply_credit_draws(events, state, [grant_at], result)
    drawn = sum(r.credits_drawn for r in result.rollups.values())
    assert drawn == pytest.approx(200.0)  # stale 62480 is not a refund
    assert [round(c) for _, c in new_lots] == [7700]  # unexplained top-up
    assert state["runmin"] == 70000.0


def test_snapshot_selection_is_monotonic_within_a_window() -> None:
    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    reset = t0 + timedelta(days=3)

    def ev(minutes: int, used: float, resets: datetime = reset) -> collector.SnapshotEvent:
        return collector.SnapshotEvent("codex", t0 + timedelta(minutes=minutes), 10080, used, resets, "pro", None)

    state: dict = {}
    kept = collector.select_snapshots([ev(0, 10), ev(1, 5), ev(2, 12), ev(3, 12), ev(30, 12)], state)
    assert [(k.used_percent) for k in kept] == [10, 12, 12]  # stale 5 dropped, heartbeat after 15 min kept
    older = collector.select_snapshots([ev(40, 1, reset - timedelta(days=7))], state)
    assert older == []


def test_snapshot_selection_lets_a_reading_without_a_reset_join_the_open_window_or_start_a_new_one() -> None:
    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    reset = t0 + timedelta(hours=2)

    def ev(minutes: int, used: float, resets: datetime | None, source: str) -> collector.SnapshotEvent:
        return collector.SnapshotEvent("claude", t0 + timedelta(minutes=minutes), 300, used, resets, None, None, source)

    state: dict = {}
    kept = collector.select_snapshots(
        [ev(0, 10, reset, "claude_statusline"), ev(30, 30, None, "workflow_attempt")], state
    )
    assert [(k.used_percent, k.resets_at, k.source) for k in kept] == [
        (10, reset, "claude_statusline"),
        (30, reset, "workflow_attempt"),
    ]
    # Three hours on, the recorded window is over: the reading has no reset to match and starts a window.
    later = collector.select_snapshots([ev(180, 4, None, "workflow_attempt")], state)
    assert [(k.used_percent, k.resets_at) for k in later] == [(4, None)]


def _plan(provider: str, usd: float | None, start: datetime, end: datetime | None) -> SimpleNamespace:
    return SimpleNamespace(provider=provider, plan="p", monthly_usd=usd, effective_from=start, effective_to=end)


def test_amortize_pro_rates_plan_changes_within_a_day() -> None:
    day = date(2026, 10, 10)
    midday = datetime(2026, 10, 10, 12).astimezone()
    plans = [
        _plan("codex", 200.0, midday - timedelta(days=30), midday),
        _plan("codex", 20.0, midday, None),
        _plan("codex", None, midday - timedelta(days=60), midday - timedelta(days=30)),
    ]
    parts = amortize(plans, day)
    assert sum(p["usd"] for p in parts) == pytest.approx(100 / 30.44 + 10 / 30.44)
    assert amortize([_plan("claude", 200.0, midday - timedelta(days=5), None)], day)[0]["usd"] == pytest.approx(6.5703, abs=1e-4)


def test_draw_down_consumes_earliest_expiry_first() -> None:
    t = datetime(2026, 10, 1, tzinfo=UTC)
    grant = SimpleNamespace(credits=100.0, granted_at=t, expires_at=t + timedelta(days=90), source="grant")
    purchase = SimpleNamespace(credits=50.0, granted_at=t - timedelta(days=1), expires_at=None, source="purchase")
    states = draw_down([purchase, grant], 120.0)
    assert [(s.lot.source, s.remaining) for s in states] == [("grant", 0.0), ("purchase", 30.0)]


def test_rates_come_from_the_catalog_rows() -> None:
    # Dated Claude ids price at their family row; the 1h cache write is 2x input.
    rate = rates.claude_rate("claude-opus-5-5-20260922")
    assert rate is not None
    assert (rate.input, rate.write_5m, rate.write_1h, rate.read, rate.output) == (4.0, 5.0, 8.0, 0.2, 20.0)
    # A Codex variant without its own credit card draws at the closest carded model.
    assert rates.codex_rate("codex/gpt-5.6-sol-daybreak-blue") == (100.0, 10.0, 500.0)
    # Haiku's long-prompt multiplier lives on its row.
    short = rates.claude_api_equiv_usd("claude-haiku-5-5", input_tokens=100_000, output_tokens=0)
    long = rates.claude_api_equiv_usd("claude-haiku-5-5", input_tokens=100_001, output_tokens=0)
    assert short == pytest.approx(0.01)
    assert long == pytest.approx(100_001 * 0.10 / 1e6 * 5)


def test_scan_reads_every_native_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    owner_home, agent_home = tmp_path / "owner", tmp_path / "agent"
    for name in ("AGENT_HUB_CODEX_SESSIONS", "AGENT_HUB_CLAUDE_PROJECTS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AGENT_HUB_NATIVE_HOMES", os.pathsep.join([str(owner_home), str(agent_home)]))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    for home, project, msg in ((owner_home, "nightshift", "m1"), (agent_home, "summitflow", "m2")):
        _jsonl(home / ".claude" / "projects" / "-srv-x" / f"{msg}.jsonl", [
            {"timestamp": "2026-10-11T12:00:00Z", "requestId": msg, "cwd": f"/srv/workspaces/projects/{project}",
             "message": {"id": msg, "model": "claude-opus-5-5", "usage": {"input_tokens": 10, "output_tokens": 5}}},
        ])
    result = collector.scan({}, now=datetime(2026, 10, 11, 13, tzinfo=UTC).timestamp())
    assert {k[3] for k in result.rollups} == {"nightshift", "summitflow"}
    assert {Path(p).parts[-5] for p in result.cursors if p.endswith(".jsonl")} == {"owner", "agent"}


def test_claude_statusline_of_every_native_home_newest_reading_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    owner_home, agent_home = tmp_path / "owner", tmp_path / "agent"
    monkeypatch.setenv("AGENT_HUB_CODEX_SESSIONS", str(tmp_path / "codex"))
    monkeypatch.setenv("AGENT_HUB_CLAUDE_PROJECTS", str(tmp_path / "claude"))
    monkeypatch.setenv("AGENT_HUB_NATIVE_HOMES", os.pathsep.join([str(Path.home()), str(agent_home)]))
    monkeypatch.setenv("XDG_STATE_HOME", str(owner_home))

    def write(base: Path, observed: int, five: float) -> None:
        f = base / "claude-usage" / "rate-limits.json" if base == owner_home else base / ".local/state/claude-usage/rate-limits.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"observed_at": observed, "rate_limits": {
            "five_hour": {"used_percentage": five, "resets_at": observed + 600},
            "seven_day": {"used_percentage": 7.0, "resets_at": observed + 6000}}}))

    now = datetime(2026, 10, 11, 13, tzinfo=UTC).timestamp()
    write(owner_home, 1_000, 10.0)
    assert [s.used_percent for s in collector.scan({}, now=now).snapshots if s.window_minutes == 300] == [10.0]
    write(agent_home, 2_000, 55.0)  # the agent user's, newer: it is the reading
    assert [s.used_percent for s in collector.scan({}, now=now).snapshots if s.window_minutes == 300] == [55.0]
    write(owner_home, 3_000, 20.0)
    assert [s.used_percent for s in collector.scan({}, now=now).snapshots if s.window_minutes == 300] == [20.0]
    (agent_home / ".local/state/claude-usage/rate-limits.json").chmod(0)  # unreadable file: skipped, not an error
    assert collector.claude_statusline_files()[1] == agent_home / ".local/state/claude-usage/rate-limits.json"


def test_project_from_cwd_strips_each_native_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_HUB_NATIVE_HOMES", os.pathsep.join(["/home/owner", "/home/agent"]))
    assert collector.project_from_cwd("/home/owner/notes/x") == "notes"
    assert collector.project_from_cwd("/home/agent/scratch/x") == "scratch"
    monkeypatch.delenv("AGENT_HUB_NATIVE_HOMES")
    assert collector.project_from_cwd("/home/agent/tmp/x") == "tmp"


def test_single_path_knobs_still_work_and_lists_split(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.utils import native_homes

    monkeypatch.setenv("AGENT_HUB_CLAUDE_PROJECTS", "/one")
    assert native_homes.claude_project_roots() == [Path("/one")]
    monkeypatch.setenv("AGENT_HUB_CODEX_SESSIONS", os.pathsep.join(["/a", "/b"]))
    assert native_homes.codex_session_roots() == [Path("/a"), Path("/b")]
    monkeypatch.delenv("AGENT_HUB_CLAUDE_PROJECTS")
    monkeypatch.delenv("AGENT_HUB_NATIVE_HOMES", raising=False)
    assert Path("/home/agent/.claude/projects") in native_homes.claude_project_roots()


def test_default_transcript_guard_admits_the_agent_users_transcripts(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.session_ingestion.adapters import transcript_parsers

    monkeypatch.delenv("AGENT_HUB_TRANSCRIPT_ROOTS")
    monkeypatch.delenv("AGENT_HUB_NATIVE_HOMES", raising=False)
    monkeypatch.delenv("AGENT_HUB_CLAUDE_PROJECTS", raising=False)
    monkeypatch.delenv("AGENT_HUB_CODEX_SESSIONS", raising=False)
    roots = transcript_parsers.transcript_roots()
    assert os.path.realpath("/home/agent/.claude/projects") in roots
    assert os.path.realpath("/home/agent/.codex/sessions") in roots
    assert transcript_parsers.contained_transcript_path("/home/agent/.claude/projects/-x/s.jsonl") is not None
