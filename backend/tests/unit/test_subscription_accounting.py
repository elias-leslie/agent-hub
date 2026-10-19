"""Subscription accounting: rates, log collection, credit draw, windows, amortization, lot draw-down."""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

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


def test_runaway_turn_context_alerts_once_and_backfill_stays_quiet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    claude = tmp_path / "claude"
    monkeypatch.setenv("AGENT_HUB_CODEX_SESSIONS", str(tmp_path / "codex"))
    monkeypatch.setenv("AGENT_HUB_CLAUDE_PROJECTS", str(claude))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    def turn(ts: datetime, n: int, ctx: int) -> dict:
        return {"timestamp": ts.isoformat(), "requestId": f"r{n}", "cwd": "/srv/workspaces/projects/x",
                "message": {"id": f"m{n}", "model": "claude-opus-5-5",
                            "usage": {"input_tokens": 5, "output_tokens": 10, "cache_read_input_tokens": ctx}}}

    now = datetime.now(UTC)
    _jsonl(claude / "p" / "subagents" / "agent-a.jsonl", [turn(now, 1, 100_000), turn(now, 2, 450_000), turn(now, 3, 460_000)])
    _jsonl(claude / "p" / "old.jsonl", [turn(now - timedelta(days=3), 1, 900_000)])
    result = collector.scan({}, now=now.timestamp())
    assert len(result.runaways) == 1
    assert "subagent" in result.runaways[0] and "450K" in result.runaways[0]


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
