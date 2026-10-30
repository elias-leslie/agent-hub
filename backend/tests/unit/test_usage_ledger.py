"""Per-call usage ledger: Claude Code (main + sub-agents), Codex (root + child threads), replay backfill,
the Sessions page fallback and the runaway spend alert."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import session_queries, usage_costs
from app.services.subscription_accounting import collector


def _jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        for rec in records:
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")  # CLI transcripts are compact


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    monkeypatch.setenv("AGENT_HUB_CODEX_SESSIONS", str(tmp_path / "codex"))
    monkeypatch.setenv("AGENT_HUB_CLAUDE_PROJECTS", str(tmp_path / "claude"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path / "claude", tmp_path / "codex"


NOW = datetime(2026, 10, 11, 13, tzinfo=UTC)


def _claude_turn(n: int, *, read: int = 0, write: int = 0, entry: str = "cli", sidechain: bool = False) -> dict:
    return {
        "timestamp": "2026-10-11T12:00:00Z", "type": "assistant", "requestId": f"r{n}", "entrypoint": entry,
        "isSidechain": sidechain, "cwd": "/srv/workspaces/projects/agent-hub",
        "message": {"id": f"m{n}", "model": "claude-opus-5-5", "usage": {
            "input_tokens": 10, "output_tokens": 100, "cache_read_input_tokens": read,
            "cache_creation_input_tokens": write,
            "cache_creation": {"ephemeral_1h_input_tokens": write, "ephemeral_5m_input_tokens": 0}}},
    }


def test_claude_main_and_subagent_calls_land_in_the_ledger(roots: tuple[Path, Path]) -> None:
    claude, _ = roots
    sid = "11111111-2222-3333-4444-555555555555"
    project = claude / "-srv-workspaces-projects-agent-hub"
    _jsonl(project / f"{sid}.jsonl", [
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": "<command-name>/clear</command-name>"}},
        {"type": "user", "message": {"role": "user", "content": "Fix the cost page"}},
        _claude_turn(1, read=50_000, write=2_000),
        _claude_turn(1, read=50_000, write=2_000),  # streamed repeat of the same message
    ])
    sub = project / sid / "subagents" / "agent-abc123.jsonl"
    _jsonl(sub, [_claude_turn(2, read=1_000, sidechain=True)])
    sub.with_suffix(".meta.json").write_text(json.dumps({"agentType": "Explore", "description": "Find the collector"}))

    result = collector.scan({}, now=NOW.timestamp())

    calls = sorted(result.calls, key=lambda c: c.key)
    assert [(c.key, c.session_id, c.agent_id) for c in calls] == [
        ("claude:m1:r1", sid, ""), ("claude:m2:r2", sid, "abc123"),
    ]
    main = calls[0]
    assert (main.input_tokens, main.cached_input_tokens, main.cache_write_tokens, main.output_tokens) == (10, 50_000, 2_000, 100)
    assert main.api_equiv_usd == pytest.approx((10 * 4 + 50_000 * 0.2 + 2_000 * 8 + 100 * 20) / 1e6)
    root = result.sessions[("claude", sid, "")]
    assert (root["kind"], root["project"], root["title"], root["job"]) == ("interactive", "agent-hub", "Fix the cost page", None)
    assert result.sessions[("claude", sid, "abc123")]["title"] == "Find the collector"


def test_scripted_claude_runs_are_routine_jobs_with_masked_names(roots: tuple[Path, Path]) -> None:
    claude, _ = roots
    for n, sid in enumerate(("a" * 8 + "-1", "b" * 8 + "-2")):
        _jsonl(claude / "p" / f"{sid}.jsonl", [
            {"type": "user", "message": {"role": "user", "content": f"Review task-9f{n}e2 at 2026-10-1{n}"}},
            _claude_turn(10 + n, entry="sdk-cli"),
        ])
    result = collector.scan({}, now=NOW.timestamp())
    jobs = {v["job"] for v in result.sessions.values()}
    assert jobs == {"agent-hub · Review # at #"}
    assert {v["kind"] for v in result.sessions.values()} == {"routine"}


def _codex_meta(own: str, *, root: str | None = None, originator: str = "codex-tui", source: object = "cli",
                hist_start: int | None = None) -> dict:
    payload: dict = {"id": own, "cwd": "/srv/workspaces/projects/neri", "originator": originator, "source": source}
    if root:
        payload |= {"session_id": root, "parent_thread_id": root}
    if hist_start is not None:
        payload["subagent_history_start_ordinal"] = hist_start
    return {"timestamp": "2026-10-11T12:00:00Z", "ordinal": 0, "type": "session_meta", "payload": payload}


def _codex_tokens(ordinal: int, total: int, inp: int, cached: int, out: int) -> dict:
    return {"timestamp": "2026-10-11T12:00:05Z", "ordinal": ordinal, "type": "event_msg", "payload": {
        "type": "token_count", "info": {"total_token_usage": {"total_tokens": total},
                                        "last_token_usage": {"input_tokens": inp, "cached_input_tokens": cached,
                                                             "output_tokens": out}}}}


def test_codex_child_thread_rolls_up_to_its_root_and_skips_inherited_history(roots: tuple[Path, Path]) -> None:
    _, codex = roots
    day = codex / "2026" / "10" / "11"
    _jsonl(day / "rollout-parent.jsonl", [
        _codex_meta("root-1", originator="codex_exec", source="exec"),
        {"timestamp": "2026-10-11T12:00:01Z", "ordinal": 1, "type": "turn_context", "payload": {"model": "gpt-6.1-sol"}},
        {"timestamp": "2026-10-11T12:00:01Z", "ordinal": 2, "type": "response_item",
         "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Nightly audit 42"}]}},
        _codex_tokens(3, 1_000, 900, 100, 100),
    ])
    spawn = {"subagent": {"thread_spawn": {"agent_path": "/root/expiry_review", "agent_role": "verifier"}}}
    _jsonl(day / "rollout-child.jsonl", [
        _codex_meta("child-1", root="root-1", source=spawn, hist_start=3),
        _codex_meta("root-1", originator="codex_exec", source="exec"),  # copied parent header
        {"timestamp": "2026-10-11T12:00:01Z", "ordinal": 1, "type": "turn_context", "payload": {"model": "gpt-6.1-sol"}},
        _codex_tokens(2, 1_000, 900, 100, 100),  # inherited parent history
        _codex_tokens(4, 300, 250, 50, 50),
    ])

    result = collector.scan({}, now=NOW.timestamp())

    by_agent = {c.agent_id: c for c in result.calls}
    assert set(by_agent) == {"", "child-1"}
    child = by_agent["child-1"]
    assert (child.session_id, child.input_tokens, child.cached_input_tokens, child.output_tokens) == ("root-1", 200, 50, 50)
    assert child.api_equiv_usd == pytest.approx((200 * 50 + 50 * 2.5 + 50 * 250) / 1e6 * 0.04)
    root = result.sessions[("codex", "root-1", "")]
    assert (root["kind"], root["project"], root["job"]) == ("routine", "neri", "neri · Nightly audit #")
    assert result.sessions[("codex", "root-1", "child-1")]["title"] == "expiry_review"


def test_a_codex_parent_that_spends_nothing_still_names_the_job_its_children_roll_into(
    roots: tuple[Path, Path],
) -> None:
    _, codex = roots
    day = codex / "2026" / "10" / "11"
    _jsonl(day / "rollout-review.jsonl", [
        _codex_meta("root-2", originator="codex_exec", source="exec"),
        {"timestamp": "2026-10-11T12:00:01Z", "ordinal": 1, "type": "response_item",
         "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Review commit 775e127"}]}},
    ])
    _jsonl(day / "rollout-reviewer.jsonl", [
        _codex_meta("child-2", root="root-2", source={"subagent": "review"}),
        _codex_tokens(1, 300, 250, 50, 50),
    ])

    result = collector.scan({}, now=NOW.timestamp())

    assert [c.agent_id for c in result.calls] == ["child-2"]
    root = result.sessions[("codex", "root-2", "")]
    assert (root["kind"], root["job"]) == ("routine", "neri · Review commit #")


def test_a_codex_review_run_without_a_prompt_is_named_after_its_target(roots: tuple[Path, Path]) -> None:
    _, codex = roots
    day = codex / "2026" / "10" / "11"
    _jsonl(day / "rollout-review.jsonl", [
        _codex_meta("root-3", originator="codex_exec", source="exec"),
        {"timestamp": "2026-10-11T12:00:01Z", "type": "event_msg",
         "payload": {"type": "item_completed", "item": {"type": "EnteredReviewMode", "user_facing_hint": "commit 8b667cb"}}},
    ])
    _jsonl(day / "rollout-reviewer.jsonl", [
        _codex_meta("child-3", root="root-3", source={"subagent": "review"}),
        _codex_tokens(1, 300, 250, 50, 50),
    ])

    result = collector.scan({}, now=NOW.timestamp())

    assert result.sessions[("codex", "root-3", "")]["job"] == "neri · Review commit #"


def test_replay_backfills_the_ledger_without_recounting_rollups(roots: tuple[Path, Path]) -> None:
    claude, _ = roots
    path = claude / "p" / "s.jsonl"
    _jsonl(path, [_claude_turn(1), _claude_turn(2)])
    first = collector.scan({}, now=NOW.timestamp())
    assert sum(r.requests for r in first.rollups.values()) == 2
    # A cursor written before the ledger existed: same offset, no ledger version.
    old = {k: (off, {s: v for s, v in st.items() if s != "ledger"}) for k, (off, st) in first.cursors.items()}

    replay = collector.scan(old, now=NOW.timestamp())
    assert sorted(c.key for c in replay.calls) == ["claude:m1:r1", "claude:m2:r2"]
    assert replay.rollups == {}
    assert replay.cursors[str(path)][1]["ledger"] == collector.LEDGER_VERSION

    _jsonl(path, [_claude_turn(3)])
    live = collector.scan(replay.cursors, now=NOW.timestamp())
    assert [c.key for c in live.calls] == ["claude:m3:r3"]
    assert sum(r.requests for r in live.rollups.values()) == 1


def test_replay_respects_the_byte_budget_and_reads_live_files_first(roots: tuple[Path, Path]) -> None:
    claude, _ = roots
    for name in ("a", "b"):
        _jsonl(claude / "p" / f"{name}.jsonl", [_claude_turn(ord(name))])
    first = collector.scan({}, now=NOW.timestamp())
    old = {k: (off, {}) for k, (off, _st) in first.cursors.items() if not k.startswith("@")}
    budgeted = collector.scan(old, now=NOW.timestamp(), byte_budget=1)
    assert len(budgeted.calls) == 1 and budgeted.replay_pending == 1


class _Rows:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def all(self) -> list[tuple]:
        return self._rows

    def __iter__(self):
        return iter(self._rows)


class _FakeDb:
    def __init__(self, *responses: list[tuple]) -> None:
        self.responses = list(responses)
        self.params: list[dict] = []

    async def execute(self, _stmt: object, params: dict | None = None) -> _Rows:
        self.params.append(params or {})
        return _Rows(self.responses.pop(0))


@pytest.mark.asyncio
async def test_sessions_without_native_usage_fall_back_to_the_ledger() -> None:
    db = _FakeDb([("native", 2, 10, 5, 1)], [], [("codex-parent", 3, 900, 60, 400)])  # rows, archives, ledger
    rollups = await session_queries.fetch_session_usage_rollups(db, ["native", "codex-parent", "empty"])
    assert db.params[2] == {"session_ids": ["codex-parent", "empty"]}
    assert rollups["native"].input_tokens == 10
    assert rollups["codex-parent"].known and rollups["codex-parent"].input_tokens == 900
    assert "empty" not in rollups


def test_chart_windows_align_to_local_bucket_edges() -> None:
    now = datetime(2026, 10, 18, 12, 34, tzinfo=UTC)
    win = usage_costs.window_for("24h", now)
    assert win.end - win.start == timedelta(hours=24) and win.end > now >= win.end - win.bucket
    assert ((win.end - win.origin) / win.bucket).is_integer()
    assert usage_costs.window_for("bogus", now).range == "24h"


def test_overview_ranks_items_filters_and_slices_one_bar(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    now = datetime(2026, 10, 18, 12, 34, tzinfo=UTC)
    win = usage_costs.window_for("24h", now)
    b1, b2 = win.end - 2 * win.bucket, win.end - win.bucket

    def row(b: datetime, item: str, kind: str, project: str, model: str, usd: float) -> SimpleNamespace:
        return SimpleNamespace(b=b, item=item, name=item, kind=kind, project=project, model=model, usd=usd,
                               tokens=100, calls=1, unpriced=0)

    rows = [row(b1, "session:claude:s1", "interactive", "agent-hub", "claude-opus-5-5", 6.0),
            row(b2, "session:claude:s1", "interactive", "agent-hub", "claude-opus-5-5", 2.0),
            row(b2, "job:neri · audit", "routine", "neri", "gpt-6.1-sol", 2.0)]

    class Db:
        async def execute(self, *_a: object, **_k: object) -> _Rows:
            return _Rows(rows)

    async def summary(*_a: object) -> dict:
        return {}

    async def cover(*_a: object) -> dict:
        return {"percent": 100.0}

    monkeypatch.setattr(usage_costs, "_summary", summary)
    monkeypatch.setattr(usage_costs, "coverage", cover)
    full = asyncio.run(usage_costs.overview(Db(), "24h", now=now))
    assert [(i["key"], i["usd"], i["share"]) for i in full["items"]] == [
        ("session:claude:s1", 8.0, 0.8), ("job:neri · audit", 2.0, 0.2)]
    assert full["chart"][-1] == {"start": b2.isoformat(), "interactive": 2.0, "routine": 2.0, "other": 0.0}
    assert full["items"][0]["spark"][-2:] == [6.0, 2.0]
    assert full["filters"]["project"] == ["agent-hub", "neri"]
    sliced = asyncio.run(usage_costs.overview(Db(), "24h", bucket_at=b2, kind="routine", now=now))
    assert [i["key"] for i in sliced["items"]] == ["job:neri · audit"]
    assert sliced["chart"][-2]["interactive"] == 0.0
