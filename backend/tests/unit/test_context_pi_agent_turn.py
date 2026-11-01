"""First turns of Pi sessions and Agent Hub agents: heads, parts, version basis."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.context_observability import agent_hub_turn, extra_capture, pi_turn
from app.services.subscription_accounting import collector

T0 = datetime(2026, 11, 1, 12, tzinfo=UTC)
DELIVERY = {
    "delivery_id": "d-1", "est_tokens": 5000, "work_role": "hunting", "coordinator": False,
    "blocks": [{"scope": "global", "tokens": 3000}, {"scope": "project", "tokens": 1000}, {"scope": "role", "tokens": 1000}],
}


def _write(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def _pi_records(*, usage: dict | None = None, sections: dict | None = None, tools: bool = True) -> list[dict]:
    system = {"role": "system", "content": "", "sections": sections or {"preamble": "p" * 400, "rules": "r" * 400, "skills": "s" * 4000}}
    if tools:
        system["toolsAdded"] = [{"name": "read", "description": "d" * 1000}]
    records = [
        {"type": "session", "id": "pi-1", "timestamp": T0.isoformat(), "cwd": "/srv/workspaces/projects/neri"},
        {"type": "model_change", "provider": "opencode-go", "modelId": "deepseek-v4.1-flash"},
        {"type": "message", "message": system},
        {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "x" * 800}]}},
    ]
    if usage is not None:
        records.append({"type": "message", "timestamp": (T0 + timedelta(seconds=3)).isoformat(),
                        "message": {"role": "assistant", "content": [], "usage": usage}})
    return records


def test_pi_head_reads_sections_tools_brief_and_the_first_counted_reply(tmp_path: Path) -> None:
    records = _pi_records(usage={"input": 0, "cacheRead": 0, "cacheWrite": 0})  # aborted reply, no count
    records.append({"type": "message", "timestamp": (T0 + timedelta(seconds=9)).isoformat(),
                    "message": {"role": "assistant", "usage": {"input": 1500, "cacheRead": 6000, "cacheWrite": 200}}})
    raw = pi_turn.read_pi_head(_write(tmp_path / "a.jsonl", records))

    assert raw is not None
    assert (raw["total"], raw["model"], raw["sid"], raw["brief_chars"]) == (7700, "deepseek-v4.1-flash", "pi-1", 800)
    assert (raw["core_chars"], raw["listing_chars"], raw["delivery_chars"]) == (800, 4000, 0)
    assert raw["tools_chars"] > 1000 and raw["first_at"] == T0 + timedelta(seconds=9) and raw["started"] == T0


def test_pi_head_is_none_before_the_first_reply(tmp_path: Path) -> None:
    assert pi_turn.read_pi_head(_write(tmp_path / "a.jsonl", _pi_records(usage=None))) is None


def test_bound_delivery_is_ours_and_the_rest_splits_by_character_weight(tmp_path: Path) -> None:
    raw = pi_turn.read_pi_head(_write(tmp_path / "a.jsonl", _pi_records(usage={"input": 8000, "cacheRead": 0, "cacheWrite": 0})))

    parts = pi_turn.compute_parts(raw, delivery=DELIVERY, launch="project")

    assert raw is not None
    assert parts["total"] == {"tokens": 8000, "method": "exact"}
    assert parts["ours"] == {"tokens": 5000, "method": "estimate"}
    assert parts["brief"]["tokens"] == 200
    assert parts["harness"] == {"tokens": 2800, "method": "derived"}
    split = [parts[n]["tokens"] for n in ("harness_core", "harness_tools", "our_listings")]
    assert sum(split) == 2800 and parts["our_listings"]["tokens"] > parts["harness_core"]["tokens"]
    assert (parts["ah_global"]["tokens"], parts["ah_project"]["tokens"], parts["ah_role"]["tokens"]) == (3000, 1000, 1000)


def test_inline_addendum_counts_as_ours_when_no_delivery_binds() -> None:
    raw = {"total": 8000, "brief_chars": 400, "core_chars": 800, "listing_chars": 0, "tools_chars": 1000, "delivery_chars": 20_000, "sections": {}}

    parts = pi_turn.compute_parts(raw, delivery=None, launch="project")

    assert parts["ours"] == {"tokens": 5000, "method": "estimate"}
    assert parts["harness"]["tokens"] == 2900


def test_nothing_unexplained_means_no_delivery_and_a_large_residual_means_unknown() -> None:
    probe = {"total": 2000, "brief_chars": 400, "core_chars": 2800, "listing_chars": 0, "tools_chars": 4000, "delivery_chars": 0, "sections": {}}
    lost = {**probe, "total": 8000}

    assert pi_turn.compute_parts(probe, delivery=None, launch="project")["ours"] == {"tokens": 0, "method": "exact"}
    parts = pi_turn.compute_parts(lost, delivery=None, launch="project")
    assert parts["ours"] == {"tokens": None, "method": "unknown"} and parts["harness"]["tokens"] is None
    assert pi_turn.compute_parts(lost, delivery=None, launch="blank")["ours"]["tokens"] == 0


def test_a_session_older_than_its_capture_is_not_claimed_as_a_live_sighting() -> None:
    assert pi_turn.version_basis(T0, T0 + timedelta(minutes=5)) == pi_turn.VERSION_BASIS_LIVE
    assert pi_turn.version_basis(T0, T0 + timedelta(days=3)) == pi_turn.VERSION_BASIS_BACKFILL


def _call(**over) -> dict:
    return {"input_tokens": 500, "cache_read": 6000, "cache_write": 500, "brief_chars": 2000, "agent_slug": "critic",
            "request_source": "summitflow", **over}


def test_agent_hub_parts_need_the_bound_delivery_before_ours_and_harness_are_claimed() -> None:
    stack = "s" * 800

    unbound = agent_hub_turn.compute_parts(_call(), stack=stack, delivery=None, stack_basis="live")
    bound = agent_hub_turn.compute_parts(_call(), stack=stack, delivery=DELIVERY, stack_basis="live")

    assert unbound["total"]["tokens"] == 7000 and unbound["brief"]["tokens"] == 500
    assert unbound["ours"]["tokens"] is None and unbound["harness"]["tokens"] is None
    assert unbound["ah_role"]["tokens"] == 200 and unbound["chars"]["delivery"] == "none"
    assert bound["ours"]["tokens"] == 5200 and bound["harness"]["tokens"] == 1300
    assert bound["ah_role"]["tokens"] == 1200 and bound["ah_global"]["tokens"] == 3000


def test_agent_hub_brief_unknown_when_events_are_gone() -> None:
    parts = agent_hub_turn.compute_parts(_call(brief_chars=None), stack="x", delivery=DELIVERY, stack_basis="live")

    assert parts["brief"]["tokens"] is None and parts["harness"]["tokens"] is None


def test_launch_mode_names_the_agent_or_its_request_source() -> None:
    assert agent_hub_turn.launch_mode_for({"agent_slug": "critic"}) == "agent:critic"
    assert agent_hub_turn.launch_mode_for({"agent_slug": None, "request_source": "nightshift.planner"}) == "agent:nightshift.planner"
    assert agent_hub_turn.launch_mode_for({}) == "agent:unknown"


async def test_a_failing_extra_capture_never_fails_the_collector_pass() -> None:
    db = AsyncMock()
    result = SimpleNamespace(sessions={("claude", "s1", ""): {}, ("claude", "s1", "a1"): {}})

    with patch.object(extra_capture, "capture_pass", AsyncMock(side_effect=RuntimeError("no table"))):
        await collector._capture_context_extra(db, result)

    db.rollback.assert_awaited_once()


async def test_extra_capture_passes_each_touched_root_session_once() -> None:
    db = AsyncMock()
    result = SimpleNamespace(sessions={("claude", "s1", ""): {}, ("claude", "s1", "a1"): {}, ("codex", "c1", ""): {}})
    seen = AsyncMock(return_value={"pi_read": 0})

    with patch.object(extra_capture, "capture_pass", seen):
        await collector._capture_context_extra(db, result)

    assert seen.await_args is not None
    assert seen.await_args.kwargs["touched"] == [("claude", "s1"), ("codex", "c1")]
    db.commit.assert_awaited_once()


def test_medians_are_upper_medians_and_a_row_of_fewer_than_three_sessions_is_marked_thin() -> None:
    from app.cli import context_backfill
    from app.services.context_observability import baseline

    assert baseline.med([8015, 8435]) == 8435 and baseline.med([3, 1, 2]) == 2 and baseline.med([None]) is None
    # the Pi coordinator row: two sessions, upper median 8,435 against 8,000: out of range, but only thin evidence
    assert context_backfill.row_status(8435, 8000, 2) == ("THIN", "8000 (out of range)")
    assert context_backfill.row_status(8435, 8000, 3) == ("FAIL", "8000")
    assert context_backfill.row_status(8100, 8000, 3) == ("PASS", "8000")
    assert context_backfill.row_status(None, 8000, 0) == ("FAIL", "unknown")


def test_agent_hub_rows_form_their_own_cost_cell() -> None:
    from app.services.context_observability import baseline

    row = baseline.FirstTurn("agent_hub", "s", "", "agent_hub", None, None, None, "agent:critic", "m", T0, 7000, None, None, 500, None, None)

    assert row.cell == "agent:critic"
