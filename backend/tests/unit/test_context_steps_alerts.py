"""Step finder, budget state and the two Nightshift notices (no database).

A step is a move of at least jump_pct that stayed; a drop is a step but never over budget; a lone odd session or
another model's rows are not steps; both notices go to the tray only and pass Nightshift's own dry-run.
"""

from __future__ import annotations

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
from app.services.context_observability.budgets import _state
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
    rows = _series(start, 30, 48400) + _series(start + timedelta(hours=8), 3, 24000, fp="fp-b")

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


def test_a_move_under_jump_pct_is_not_flagged_and_a_version_step_is_named_a_version_step():
    start = NOW - timedelta(days=3)
    small = _series(start, 20, 48000) + _series(start + timedelta(hours=8), 3, 50000, version="2.1.317")
    big = _series(start, 20, 48000) + _series(start + timedelta(hours=8), 3, 60000, version="2.1.317", fp="fp-a")

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
    jumped = _state("claude", "implementation", base + _series(NOW - timedelta(hours=5), 3, 26000), policy, NOW)
    dropped = _state("claude", "implementation", _series(NOW - timedelta(days=5), 10, 28000) + _series(NOW - timedelta(hours=5), 3, 10000), policy, NOW)
    thin = _state("claude", "implementation", base + _series(NOW - timedelta(hours=5), 2, 90000), policy, NOW)
    under = _state("claude", "implementation", base + _series(NOW - timedelta(hours=5), 3, 21000), policy, NOW)

    assert (over.reason, jumped.reason, dropped.reason, thin.reason, under.reason) == ("warn", "jump", None, None, None)
    assert round(jumped.pct) == 30 and over.warn_tokens == 30000


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


def _why() -> Why:
    return Why(harness="claude", role="lane", at=NOW, kind="config", cause="config", before=None, after=None, delta=-24400, pct=-50,
               parts={"harness": -24000, "ours": 0, "brief": 0}, version={"from": "2.1.316", "to": "2.1.316"},
               knobs=[SimpleNamespace(label="lane-tools.json")], summary="claude lane: 48.4K -> 24.0K")


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
    from app.services.context_observability.budgets import CellState

    state = CellState("claude", "implementation", 5, 31000, 30, 24000, 30000, 25, 29.0, "warn")
    notice = alerts.budget_notice(state, _why(), _policy(Budget("*", "*", 30000), knobs=(Knob("lane-tools.json", "claude", "*", "/r", "f", None),)))

    assert notice["push"] == "tray" and notice["key"] == "agent-hub-context-budget:claude:implementation"
    assert "Knob: lane-tools.json" in notice["body"] and "config changed" in notice["body"] and "over its 30.0K budget" in notice["body"]
    assert notice["actions"][0] == notice["primary"] == "look-into"
    assert alerts.budget_key("claude", "subagent:general-purpose").endswith("claude:subagent:general-purpose")


@pytest.mark.skipif(shutil.which("nightshift") is None, reason="nightshift not on PATH")
def test_both_notices_pass_nightshifts_dry_run_on_the_tray_route():
    from app.services.context_observability.budgets import CellState

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
