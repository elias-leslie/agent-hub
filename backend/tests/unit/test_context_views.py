"""Cost matrix, daily series and version sightings (no database).

Unknown stays None: a cell with too few starts on either side has no change, an unmeasured part is not 0.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.context_observability import views
from app.services.context_observability.baseline import FirstTurn
from app.services.context_observability.budgets import _state
from app.services.context_observability.policy import Budget, Policy

NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)
POLICY = Policy(budgets=(Budget("*", "*", 60000), Budget("pi", "*", 12000)), jump_pct=25, knobs=())


def _turn(at: datetime, total: int, *, harness: str = "claude", role: str | None = "implementation", mode: str = "project",
          version: str | None = "2.1.316", model: str = "opus", parts: tuple[int | None, int | None, int | None] = (30000, 5000, 100)) -> FirstTurn:
    h, o, b = parts
    return FirstTurn(provider=harness, session_id=f"s{at.timestamp()}-{role}-{harness}", agent_id="", harness=harness, version=version, role=role,
                     coordinator=False, launch_mode=mode, model=model, at=at, total=total, harness_tokens=h, ours_tokens=o, brief_tokens=b,
                     config_fp="fp", delivery_id=None)


def _series(start: datetime, n: int, total: int, **kw) -> list[FirstTurn]:
    return [_turn(start + timedelta(minutes=10 * i), total, **kw) for i in range(n)]


def _matrix(rows: list[FirstTurn], days: int = 7):
    states = [_state(h, c, [r for r in rows if (r.harness, r.cell) == (h, c)], POLICY, NOW) for h, c in sorted({(r.harness, r.cell) for r in rows})]
    return views.build_matrix(rows, POLICY, states, days=days, now=NOW)


def test_a_cell_has_its_medians_the_change_against_the_window_before_and_its_budget():
    rows = _series(NOW - timedelta(days=12), 5, 40000) + _series(NOW - timedelta(days=3), 5, 50000)

    (cell,) = _matrix(rows).cells

    assert (cell.harness, cell.cell, cell.n, cell.total, cell.prev_n, cell.prev_total) == ("claude", "implementation", 5, 50000, 5, 40000)
    assert (cell.delta, cell.delta_pct, cell.warn_tokens, cell.flag) == (10000, 25.0, 60000, "jump")  # the shown +25% is the jump rule
    assert (cell.harness_tokens, cell.ours, cell.brief) == (30000, 5000, 100)


def test_one_rule_flags_the_shown_change_and_a_held_back_change_says_why():
    big = _series(NOW - timedelta(days=12), 6, 30000, role="implementation") + _series(NOW - timedelta(days=3), 6, 42000, role="implementation")
    thin = _series(NOW - timedelta(days=12), 3, 30000, role="research") + _series(NOW - timedelta(days=3), 6, 42000, role="research")
    small = _series(NOW - timedelta(days=12), 6, 30000, role="review") + _series(NOW - timedelta(days=3), 6, 33000, role="review")

    cells = {c.cell: c for c in _matrix(big + thin + small).cells}

    assert (cells["implementation"].flag, cells["implementation"].flag_held) == ("jump", None)  # +40% with 6 starts each side
    assert cells["research"].flag is None and "only 6 and 3 starts" in (cells["research"].flag_held or "")
    assert (cells["review"].flag, cells["review"].flag_held) == (None, None)  # +10%


def test_too_few_starts_on_either_side_show_the_median_but_no_change():
    rows = _series(NOW - timedelta(days=12), 2, 40000) + _series(NOW - timedelta(days=3), 5, 50000)
    thin_now = _series(NOW - timedelta(days=12), 5, 40000, role="research") + _series(NOW - timedelta(days=3), 2, 50000, role="research")

    cells = {c.cell: c for c in _matrix(rows + thin_now).cells}

    assert (cells["implementation"].total, cells["implementation"].delta, cells["implementation"].delta_pct) == (50000, None, None)
    assert (cells["research"].total, cells["research"].n, cells["research"].delta) == (50000, 2, None)


def test_an_unmeasured_part_is_none_not_zero_and_a_cell_outside_the_window_is_left_out():
    rows = _series(NOW - timedelta(days=2), 4, 8000, harness="pi", role="review", parts=(None, None, 90))
    rows += _series(NOW - timedelta(days=10), 4, 9000, harness="pi", role="research")  # only in the previous window

    (cell,) = _matrix(rows).cells

    assert (cell.harness, cell.cell, cell.total, cell.harness_tokens, cell.ours, cell.brief) == ("pi", "review", 8000, None, None, 90)
    assert cell.warn_tokens == 12000


def test_the_over_budget_flag_comes_from_the_last_day_and_the_cell_name_is_the_launch_table_role_or_launch_mode():
    rows = _series(NOW - timedelta(hours=5), 4, 70000, role="coordinator")
    rows += _series(NOW - timedelta(hours=5), 3, 9000, role=None, mode="subagent:Explore")
    rows += _series(NOW - timedelta(hours=5), 3, 2000, role=None, mode="blank", harness="pi")
    rows += _series(NOW - timedelta(hours=5), 3, 7000, role=None)

    cells = {(c.harness, c.cell): c for c in _matrix(rows).cells}

    assert set(cells) == {("claude", "coordinator"), ("claude", "subagent:Explore"), ("pi", "blank"), ("claude", "unknown")}
    assert cells[("claude", "coordinator")].flag == "warn" and cells[("claude", "coordinator")].recent == 70000
    assert cells[("claude", "unknown")].flag is None


def test_harness_version_is_the_one_that_appeared_last_not_the_one_a_sub_agent_still_runs():
    rows = _series(NOW - timedelta(days=3), 4, 40000, version="2.1.314")
    rows += _series(NOW - timedelta(days=1), 4, 40000, version="2.1.316")
    rows += [_turn(NOW - timedelta(minutes=5), 10000, version="2.1.314", role=None, mode="subagent:Explore")]  # newest start, older version

    (info,) = _matrix(rows).harnesses

    assert (info.harness, info.version, info.n) == ("claude", "2.1.316", 9)


def test_daily_medians_and_version_sightings_mark_the_first_version_as_already_running():
    rows = _series(NOW - timedelta(days=3), 3, 40000, version="2.1.314") + _series(NOW - timedelta(days=1), 3, 20000, version="2.1.316")
    rows += _series(NOW - timedelta(days=1, minutes=-60), 2, 20000, version=None)

    days = views.daily_series(rows)
    seen = views.version_sightings(rows)

    assert [(d.day, d.n, d.total) for d in days] == [("2026-10-30", 3, 40000), ("2026-11-01", 5, 20000)]
    assert [(v.version, v.initial, v.n) for v in seen] == [("2.1.314", True, 3), ("2.1.316", False, 3)]


def test_the_headline_compares_the_same_model_only():
    window = _series(NOW - timedelta(days=2), 4, 30000)
    previous = _series(NOW - timedelta(days=9), 4, 60000) + _series(NOW - timedelta(days=9), 4, 10000, model="haiku")

    head = views.headline(window, previous)

    assert (head.total, head.prev_n, head.prev_total, head.delta, head.delta_pct) == (30000, 4, 60000, -30000, -50.0)
    assert views.headline(window, []).delta is None


def test_thinning_keeps_the_ends_in_order():
    items = list(range(5000))
    thin = views._thin(items, 2000)
    assert len(thin) == 2000 and thin[0] == 0 and thin == sorted(thin)
