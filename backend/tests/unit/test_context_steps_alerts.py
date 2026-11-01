"""Step finder, budget state and the two Nightshift notices (no database).

A step is a move of at least jump_pct that stayed; a drop is a step but never over budget; a lone odd session or
another model's rows are not steps; both notices go to the tray only and pass Nightshift's own dry-run.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.context_observability import alerts, steps
from app.services.context_observability.baseline import FirstTurn
from app.services.context_observability.budgets import CellState, _state
from app.services.context_observability.policy import Budget, Knob, Policy
from app.services.context_observability.why import Why

NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)
FIND = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "a7c3e9d41b52_context_budgets_knobs_markers.py"


def _turn(at: datetime, total: int, *, fp: str = "fp-a", version: str = "2.1.316", model: str = "opus", role: str = "implementation",
          harness: str = "claude", mode: str = "project", ours: int = 5000) -> FirstTurn:
    return FirstTurn(provider=harness, session_id=f"s{at.timestamp()}", agent_id="", harness=harness, version=version, role=role,
                     coordinator=False, launch_mode=mode, model=model, at=at, total=total, harness_tokens=total - ours - 100,
                     ours_tokens=ours, brief_tokens=100, config_fp=fp, delivery_id=None)


def _series(start: datetime, n: int, total: int, **kw) -> list[FirstTurn]:
    return [_turn(start + timedelta(minutes=10 * i), total, **kw) for i in range(n)]


def _policy(*budgets: Budget, jump: int | None = 25, knobs: tuple[Knob, ...] = ()) -> Policy:
    return Policy(budgets=budgets, jump_pct=jump, knobs=knobs)


def test_a_config_change_that_stays_is_a_step_even_with_the_version_unchanged():
    start = NOW - timedelta(days=3)
    rows = _series(start, 30, 48400) + _series(start + timedelta(hours=8), 5, 24000, fp="fp-b")

    (step,) = steps.find_steps(rows, 25)

    assert (step.kind, step.at, step.delta, round(step.pct)) == ("config", start + timedelta(hours=8), -24400, -50)
    assert (step.before.version, step.after.version) == ("2.1.316", "2.1.316")
    assert (step.before.config_fp, step.after.config_fp) == ("fp-a", "fp-b")


def test_one_odd_session_and_another_models_rows_are_not_steps():
    start = NOW - timedelta(days=3)
    rows = _series(start, 30, 48400)
    rows.append(_turn(start + timedelta(hours=6), 24000, fp="fp-b"))  # a single session on another fingerprint
    rows += _series(start + timedelta(minutes=3), 20, 28000, model="haiku", fp="fp-h")  # a cheaper model interleaved

    assert steps.find_steps(rows, 25) == []


def test_two_kinds_of_session_that_swap_places_make_one_step_not_one_per_swap():
    start = NOW - timedelta(days=3)
    rows = _series(start, 40, 30000)  # the usual sessions
    for i in range(4):  # a second kind (another version still open, another tool set) swaps in and out in runs
        rows += _series(start + timedelta(hours=8 + 2 * i), 6, 45000, fp="fp-b", version="2.1.314")
        rows += _series(start + timedelta(hours=8 + 2 * i, minutes=70), 6, 30000)

    found = steps.find_step_rows(rows, 25)

    assert len(found) == 1 and found[0].step.kind == "config"  # only the first sighting of the second kind


def test_a_step_carries_the_starts_on_each_side_and_they_are_the_windows_it_reports():
    start = NOW - timedelta(days=3)
    rows = _series(start, 30, 48400) + _series(start + timedelta(hours=8), 5, 24000, fp="fp-b")

    (found,) = steps.find_step_rows(rows, 25)

    assert (len(found.before_rows), len(found.after_rows)) == (found.step.before.n, found.step.after.n) == (30, 5)
    assert all(r.config_fp == "fp-b" for r in found.after_rows)


def test_a_dip_that_is_not_a_step_says_why():
    first = NOW - timedelta(days=4)
    rows = _series(first, 1, 48000) + _series(first + timedelta(days=1), 16, 29000) + _series(first + timedelta(days=2), 40, 48000)
    steps_found = steps.find_step_rows(rows, 25)

    (dip,) = [d for d in steps.find_dips(rows, 25, steps_found) if d.day == (first + timedelta(days=1)).date()]

    assert round(dip.pct) == -40 and (dip.n_day, dip.n_before) == (16, 1)
    assert "only 1 start in the week before" in dip.reason and "needs 5" in dip.reason


def test_a_move_under_jump_pct_is_not_flagged_and_a_version_step_is_named_a_version_step():
    start = NOW - timedelta(days=3)
    small = _series(start, 20, 48000) + _series(start + timedelta(hours=8), 5, 50000, version="2.1.317")
    big = _series(start, 20, 48000) + _series(start + timedelta(hours=8), 5, 60000, version="2.1.317", fp="fp-a")

    assert steps.find_steps(small, 25) == []
    (step,) = steps.find_steps(big, 25)
    assert (step.kind, step.pct) == ("version", 25.0)


def test_growth_with_no_marker_is_found_as_a_day_step():
    start = NOW - timedelta(days=5)
    rows = _series(start, 40, 20000) + _series(NOW - timedelta(days=1), 6, 30000)

    (step,) = steps.find_steps(rows, 25)

    assert step.kind == "day" and step.delta == 10000


def test_lane_means_every_launched_role_but_the_coordinator():
    rows = [_turn(NOW, 1, role="implementation"), _turn(NOW, 2, role="research"), _turn(NOW, 3, role="coordinator"),
            _turn(NOW, 4, mode="blank", role="implementation"), _turn(NOW, 5, harness="codex")]

    assert [r.total for r in steps.cell_rows(rows, "claude", "lane")] == [1, 2]
    assert [r.total for r in steps.cell_rows(rows, "claude", "coordinator")] == [3]


def _warn(policy: Policy, harness: str, role: str) -> int | None:
    budget = policy.budget_for(harness, role)
    return None if budget is None else budget.warn_tokens


def test_the_most_specific_budget_row_wins():
    policy = _policy(Budget("*", "*", 60000), Budget("claude", "*", 55000), Budget("*", "blank", 20000), Budget("claude", "blank", 15000))

    assert _warn(policy, "claude", "blank") == 15000
    assert _warn(policy, "claude", "lane") == 55000
    assert _warn(policy, "codex", "blank") == 20000
    assert _warn(policy, "codex", "lane") == 60000
    assert _policy().budget_for("pi", "x") is None


def test_a_cell_is_over_above_its_warn_level_and_a_rise_over_the_jump_but_never_a_drop():
    policy = _policy(Budget("*", "*", 30000))
    base = _series(NOW - timedelta(days=5), 10, 20000)

    over = _state("claude", "implementation", base + _series(NOW - timedelta(hours=5), 3, 31000), policy, NOW)
    jumped = _state("claude", "implementation", base + _series(NOW - timedelta(hours=5), 5, 26000), policy, NOW)
    dropped = _state("claude", "implementation", _series(NOW - timedelta(days=5), 10, 28000) + _series(NOW - timedelta(hours=5), 3, 10000), policy, NOW)
    thin = _state("claude", "implementation", base + _series(NOW - timedelta(hours=5), 2, 90000), policy, NOW)
    under = _state("claude", "implementation", base + _series(NOW - timedelta(hours=5), 3, 21000), policy, NOW)

    assert (over.reason, jumped.reason, dropped.reason, thin.reason, under.reason) == ("warn", "jump", None, None, None)
    assert round(jumped.body_pct) == 30 and over.warn_tokens == 30000


def test_a_jump_is_judged_within_one_model():
    policy = _policy(Budget("*", "*", 90000))
    opus = _series(NOW - timedelta(days=5), 10, 48000)
    haiku_recent = _series(NOW - timedelta(hours=5), 4, 28000, model="haiku")

    assert _state("claude", "implementation", opus + haiku_recent, policy, NOW).reason is None


def test_default_budgets_sit_above_the_medians_of_2026_11_01_and_the_global_row_carries_the_jump():
    spec = importlib.util.spec_from_file_location("budget_migration", FIND)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    medians = {"claude": 48400, "codex": 22300, "pi": 8400}  # highest cell median of each harness (DESIGN section 2)
    policy = _policy(*(Budget(h, r, w) for h, r, w, _, _ in migration.BUDGETS))

    for harness, median in medians.items():
        assert (_warn(policy, harness, "any") or 0) > median
    assert (_warn(policy, "antigravity", "any") or 0) > max(medians.values())
    assert [(h, r) for h, r, _, j, _ in migration.BUDGETS if j is not None] == [("*", "*")]


def _queue(count: int, global_count: int = 2, per_day: int = 412) -> SimpleNamespace:
    row = SimpleNamespace(scope_after="global reference", target_kind="memory", title="Test with Haiku agents",
                          writers=[SimpleNamespace(session="aico-widget-lane")])
    return SimpleNamespace(summary=SimpleNamespace(count=count, by_kind={"memory": count - 1, "prompt": 1}, global_count=global_count,
                                                   tokens_per_day=per_day), rows=[row] * count)


def _why(cause: str = "config", delta: int = 7000, pct: float = 29.0, knobs: tuple[str, ...] = ("lane-tools.json",), **parts: int | None) -> Why:
    return Why(harness="claude", role="lane", at=NOW, kind="recent", cause=cause, before=None, after=None, delta=delta, pct=pct,
               parts={"harness": 6900, "ours": 0, "brief": 0, **parts}, version={"from": "2.1.316", "to": "2.1.316"},
               knobs=[SimpleNamespace(label=k) for k in knobs], summary="claude lane: 24.0K -> 31.0K")


def _dry_run(notice: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["nightshift", "push", "--json", "--dry-run"], input=json.dumps(notice), capture_output=True, text=True,
                          timeout=30, check=False)


def test_the_review_item_is_one_rolling_todo_for_the_tray():
    notice = alerts.review_notice(_queue(4))


    assert (notice["key"], notice["kind"], notice["push"], notice["cooldown"]) == ("agent-hub-context-review", "todo", "tray", 0)
    assert notice["title"] == "4 context changes to review"
    assert notice["body"].startswith("3 memories, 1 prompt;") and "2 reach every session" in notice["body"] and "+412 tokens a day" in notice["body"]
    assert notice["actions"] == ["open", "done"] and notice["primary"] == "open"


def test_the_budget_item_names_the_cause_and_the_knob_and_goes_to_the_tray():
    state = CellState("claude", "implementation", 5, 31000, 30, 24000, 30000, 25, 29.0, "warn")
    notice = alerts.budget_notice(state, _why(), _policy(Budget("*", "*", 30000), knobs=(Knob("lane-tools.json", "claude", "*", "/r", "f", None),)))

    assert notice["push"] == "tray" and notice["key"] == "agent-hub-context-budget:claude:implementation"
    assert "Knob: lane-tools.json" in notice["body"] and "config changed" in notice["body"] and "over its 30.0K budget" in notice["body"]
    assert notice["actions"][0] == notice["primary"] == "look-into"
    assert alerts.budget_key("claude", "subagent:general-purpose").endswith("claude:subagent:general-purpose")


@pytest.mark.skipif(shutil.which("nightshift") is None, reason="nightshift not on PATH")
def test_both_notices_pass_nightshifts_dry_run_on_the_tray_route():
    state = CellState("claude", "lane", 5, 38000, 30, 24000, 30000, 25, 58.0, "jump")
    for notice in (alerts.review_notice(_queue(3)), alerts.budget_notice(state, _why(), _policy(Budget("*", "*", 60000)))):
        result = _dry_run(notice)
        assert result.returncode == 0, result.stderr or result.stdout
        echoed = json.loads(result.stdout)
        assert (echoed["push"], echoed["key"], echoed["severity"]) == ("tray", notice["key"], "warning")


@pytest.mark.asyncio
async def test_a_failing_alert_pass_never_fails_the_collector_pass():
    from unittest.mock import AsyncMock, patch

    from app.services.subscription_accounting import collector

    db = AsyncMock()
    with patch.object(alerts, "evaluate", new=AsyncMock(side_effect=RuntimeError("table missing"))):
        await collector._evaluate_context_alerts(db)
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()
    with patch.object(alerts, "evaluate", new=AsyncMock(return_value={"k": "pushed"})) as evaluate:
        await collector._evaluate_context_alerts(db)
    evaluate.assert_awaited_once()
    db.commit.assert_awaited_once()


# ---- review fixes (M3 review): unknown is not zero, only changed knobs, hysteresis, small samples, lane scope ----


def _cause(**kw: object) -> str:
    from app.services.context_observability.why import _cause as cause

    base = dict(delta=8000, ours=None, harness=None, brief=None, version_changed=False, fp_changed=False, knob_changed=False, model_changed=False)
    return cause(**{**base, **kw})


def test_a_part_that_is_not_known_is_never_counted_as_zero():
    assert _cause(ours=300) == "unknown"  # harness and brief unknown, ours +0.3K of +8K: not "ours"
    assert _cause() == "unknown" and _cause(delta=None, ours=1, harness=1, brief=1) == "unknown"
    assert _cause(ours=1000, harness=6800, brief=100, fp_changed=True) == "config"  # known parts cover the move
    assert _cause(ours=6000, harness=None, brief=0) == "ours"
    assert _cause(delta=8000, ours=100, harness=100, brief=100, model_changed=True) == "model"
    assert _cause(delta=0, ours=0, harness=0, brief=0) == "none"
    assert _cause(ours=3000, harness=3000, brief=None, delta=6000) == "mixed"  # two parts of equal size: not told apart


def test_a_cause_is_never_picked_by_size_alone_when_several_things_changed_at_once():
    # claude subagent:general-purpose, 2026-10-31 13:14Z: model, config_fp and version all changed; harness +5.4K, ours +5.9K
    changed = dict(delta=11300, ours=5900, harness=5400, brief=0, model_changed=True, fp_changed=True, version_changed=True)
    assert _cause(**changed) == "mixed"
    assert _cause(**{**changed, "ours": 600}) == "unknown"  # harness leads, but another model came with a new version
    assert _cause(**{**changed, "ours": 600, "model_changed": False, "fp_changed": False}) == "harness_version"
    assert _cause(ours=5900, harness=5400, brief=0, delta=11300) == "mixed"  # even with nothing else changed


def test_a_knob_and_a_version_that_changed_together_are_not_told_apart_and_a_version_alone_is_the_version():
    kw = dict(ours=0, brief=0, harness=8000, fp_changed=True)
    assert _cause(**kw, version_changed=True, knob_changed=True) == "unknown"
    assert _cause(**kw, version_changed=True) == "harness_version"
    assert _cause(**kw, knob_changed=True) == "config"
    assert _cause(**{**kw, "fp_changed": False}) == "harness"


def test_a_card_names_only_a_knob_that_changed():
    policy = _policy(Budget("*", "*", 30000), knobs=(Knob("lane-tools.json", "claude", "*", "/r", "f", None),))
    state = CellState("claude", "implementation", 5, 31000, 30, 24000, 30000, 25, 29.0, "warn")

    ours = alerts.budget_notice(state, _why("ours", knobs=(), ours=6900, harness=0), policy)
    vendor = alerts.budget_notice(state, _why("config", knobs=()), policy)
    unknown = alerts.budget_notice(state, _why("unknown", knobs=("lane-tools.json",), harness=None), policy)

    assert "Knob: no knob of ours changed." in ours["body"] and "lane-tools.json" not in ours["body"]
    assert "Knob: no knob of ours changed." in vendor["body"] and "no change of ours" in vendor["body"]
    assert "not pinned down" in unknown["body"] and "Harness n/a" in unknown["body"]
    assert "Cause: not worked out. Knob: not checked." in alerts.budget_notice(state, None, policy)["body"]


def test_an_over_budget_cell_with_no_recent_rise_says_so_instead_of_blaming_an_old_step():
    policy = _policy(Budget("*", "*", 30000))
    state = CellState("claude", "implementation", 5, 31000, 30, 31000, 30000, 25, 0.0, "warn")

    notice = alerts.budget_notice(state, _why("harness", delta=-24400, pct=-50), policy)

    assert "no rise in the last day" in notice["body"] and "Harness -" not in notice["body"]


def test_knobs_and_budget_rows_resolve_the_lane_group_for_a_lane_cell_only():
    policy = _policy(Budget("*", "*", 60000), Budget("claude", "lane", 40000), Budget("*", "coordinator", 20000), Budget("claude", "*", 55000),
                     knobs=(Knob("lane-tools.json", "claude", "lane", "/r", "f", None),))

    assert [k.name for k in policy.knobs_for("claude", "implementation")] == ["lane-tools.json"]
    assert [k.name for k in policy.knobs_for("claude", "lane")] == ["lane-tools.json"]
    for other in ("coordinator", "exec:coordinator", "blank", "subagent:general-purpose", "unknown"):
        assert policy.knobs_for("claude", other) == []
    assert _warn(policy, "claude", "implementation") == 40000  # a "lane" row reaches a lane cell
    assert _warn(policy, "codex", "implementation") == 60000
    assert _warn(policy, "claude", "coordinator") == 20000  # a role row beats the harness row, for every harness
    assert _warn(policy, "claude", "blank") == 55000


def test_a_cell_inside_the_hysteresis_band_is_neither_over_nor_clear_and_thin_data_says_nothing():
    policy = _policy(Budget("*", "*", 60000))
    base = _series(NOW - timedelta(days=5), 10, 55000)

    def at(total: int, n: int = 3):
        return _state("claude", "implementation", base + _series(NOW - timedelta(hours=5), n, total), policy, NOW)

    band, clear, over, thin = at(57000), at(50000), at(61000), at(30000, 2)
    assert (band.reason, band.warn_clear) == (None, False)  # 95% of the level: still open if it was
    assert (clear.reason, clear.warn_clear) == (None, True)
    assert (over.reason, over.warn_clear) == ("warn", False)
    assert (thin.reason, thin.warn_clear, thin.jump_clear) == (None, None, None)  # two starts: unknown, not "under"


def test_a_jump_clears_below_half_of_jump_pct_and_not_on_thin_baselines():
    policy = _policy(Budget("*", "*", 90000))
    base = _series(NOW - timedelta(days=5), 10, 20000)

    def at(total: int, n: int = 5, history=base):
        return _state("claude", "implementation", history + _series(NOW - timedelta(hours=5), n, total), policy, NOW)

    assert (at(26000).reason, at(26000).jump_clear) == ("jump", False)
    assert (at(21000).reason, at(21000).jump_clear) == (None, True)  # +5%, under 12.5%
    assert (at(22800).reason, at(22800).jump_clear) == (None, False)  # +14%: between half and the full jump
    assert at(26000, history=base[:4]).jump_clear is None  # four starts before: too few to say


def test_a_jump_needs_five_starts_each_side_and_ignores_the_brief():
    policy = _policy(Budget("*", "*", 90000))
    base = _series(NOW - timedelta(days=5), 10, 20000)
    four = _state("claude", "implementation", base + _series(NOW - timedelta(hours=5), 4, 30000), policy, NOW)
    five = _state("claude", "implementation", base + _series(NOW - timedelta(hours=5), 5, 30000), policy, NOW)
    pasted = [dataclasses.replace(r, brief_tokens=10100) for r in _series(NOW - timedelta(hours=5), 5, 30000)]
    long_brief = _state("claude", "implementation", base + pasted, policy, NOW)

    assert (four.reason, five.reason) == (None, "jump")
    assert long_brief.reason is None and round(long_brief.body_pct or 0) == 0  # 20.1K without the brief against 19.9K


def test_a_step_needs_five_starts_each_side_and_does_not_see_a_pasted_brief():
    start = NOW - timedelta(days=3)
    few_after = _series(start, 30, 48400) + _series(start + timedelta(hours=8), 4, 24000, fp="fp-b")
    few_before = _series(start, 4, 48400) + _series(start + timedelta(hours=8), 8, 24000, fp="fp-b")
    brief_only = _series(start, 30, 20000) + [_turn(start + timedelta(hours=8, minutes=i), 30000, fp="fp-b") for i in range(8)]
    brief_only = [dataclasses.replace(r, brief_tokens=10100) if r.at >= start + timedelta(hours=8) else r for r in brief_only]

    assert steps.find_steps(few_after, 25) == []
    assert steps.find_steps(few_before, 25) == []
    assert steps.find_steps(brief_only, 25) == []  # +50% in total, +0% without the brief


def test_a_budget_item_stays_open_when_there_is_too_little_data_and_closes_only_when_clear():
    from app.services.context_observability.alerts import Sent, _budget_verdict

    def cell(**kw):
        return CellState("claude", "implementation", 3, 50000, 8, 50000, 60000, 25, None, None, **kw)

    open_warn = Sent(open=True, sent_at=NOW - timedelta(hours=2), reason="warn")
    assert _budget_verdict(None, open_warn, NOW) == ("wait", "warn")  # no rows at all: not "back under"
    assert _budget_verdict(cell(), open_warn, NOW) == ("wait", "warn")  # three starts become two overnight: still open
    assert _budget_verdict(cell(warn_clear=False), open_warn, NOW) == ("hold", "warn")
    assert _budget_verdict(cell(warn_clear=True), open_warn, NOW) == ("clear", "warn")
    assert _budget_verdict(cell(warn_clear=True, jump_clear=False), Sent(True, NOW, "jump"), NOW) == ("hold", "jump")
    assert _budget_verdict(None, Sent(True, NOW - timedelta(days=9), "warn"), NOW)[0] == "clear"  # nothing to judge by for 8 days
    assert _budget_verdict(None, None, NOW)[0] == "idle"
    over = CellState("claude", "implementation", 5, 70000, 8, 50000, 60000, 25, 40.0, "warn", False, False)
    assert _budget_verdict(over, open_warn, NOW) == ("over", "warn")


@pytest.mark.asyncio
async def test_a_pass_stops_sending_after_the_first_failure_and_never_waits_past_its_budget():
    import asyncio

    calls: list[str] = []

    async def slow() -> bool:
        calls.append("slow")
        await asyncio.sleep(5)
        return True

    async def fine() -> bool:
        calls.append("fine")
        return True

    hung = alerts.Sender(budget_s=0.05)
    assert await hung.run(slow) is False and await hung.run(fine) is None  # a hung nightshift costs one call, the rest wait
    failing = alerts.Sender(budget_s=5)

    async def refused() -> bool:
        return False

    assert await failing.run(refused) is False and await failing.run(fine) is None
    assert calls == ["slow"]
    assert await alerts.Sender(budget_s=5).run(fine) is True
    assert await alerts.Sender(budget_s=0).run(fine) is None  # no time left: nothing starts
