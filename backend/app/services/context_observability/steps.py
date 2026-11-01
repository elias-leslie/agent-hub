"""Step finder: where a cell's first-turn size moved by at least jump_pct, and what changed there.

A cell is one (harness, role) of the Cost matrix. Rows are split by model first, so a day of Haiku lanes is never read
as a drop in Opus lanes. Two detectors:
  - a boundary step: the config fingerprint or the harness version changed and stayed (at least MIN_AFTER starts), so
    the size before it (the 7 days up to it) is compared with the size after;
  - a day step: a day's median (at least MIN_DAY starts) against the 7 days before it, for growth no marker explains.
`markers` on a step are filled by the caller (they need the database and git).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import pairwise

from .baseline import FirstTurn, cell_label, med
from .markers import Marker

BASELINE_DAYS = 7
MIN_AFTER = 2  # starts a new fingerprint or version needs to count as a change that stayed
MIN_DAY = 3  # starts a day needs to have a median of its own
MIN_BASELINE = 5

# "lane" is the owner's word for any launched project session that is not the coordinator.
ROLE_GROUPS = {"lane": lambda mode, role: mode in ("project", "exec") and role not in (None, "coordinator")}


@dataclass(frozen=True)
class Window:
    n: int
    total: int | None
    harness: int | None
    ours: int | None
    brief: int | None
    version: str | None
    config_fp: str | None
    model: str | None
    start: datetime | None
    end: datetime | None


@dataclass
class Step:
    at: datetime
    kind: str  # config | version | day
    model: str | None
    role: str  # the cell the step was seen in (a "lane" query gets one step per lane role)
    before: Window
    after: Window
    delta: int
    pct: float
    markers: list[Marker] = field(default_factory=list)


def cell_rows(rows: list[FirstTurn], harness: str, role: str) -> list[FirstTurn]:
    """First turns of one harness whose cell is `role` (or the group "lane")."""
    group = ROLE_GROUPS.get(role)
    return [r for r in rows if r.harness == harness and (group(r.launch_mode, r.role) if group else r.cell == role)]


def _dominant(values: list[str | None]) -> str | None:
    known = [v for v in values if v]
    return Counter(known).most_common(1)[0][0] if known else None


def window(rows: list[FirstTurn]) -> Window:
    return Window(
        n=len(rows), total=med(r.total for r in rows), harness=med(r.harness_tokens for r in rows),
        ours=med(r.ours_tokens for r in rows), brief=med(r.brief_tokens for r in rows),
        version=_dominant([r.version for r in rows]), config_fp=_dominant([r.config_fp for r in rows]),
        model=_dominant([r.model for r in rows]),
        start=min((r.at for r in rows), default=None), end=max((r.at for r in rows), default=None),
    )


def _state(row: FirstTurn) -> tuple[str, str]:
    return (row.config_fp or "", row.version or "")


def _runs(rows: list[FirstTurn]) -> list[list[FirstTurn]]:
    """Consecutive rows with one (fingerprint, version), runs under MIN_AFTER dropped and equal neighbours merged."""
    runs: list[list[FirstTurn]] = []
    for row in rows:
        if runs and _state(runs[-1][0]) == _state(row):
            runs[-1].append(row)
        else:
            runs.append([row])
    kept = [run for run in runs if len(run) >= MIN_AFTER]
    merged: list[list[FirstTurn]] = []
    for run in kept:
        if merged and _state(merged[-1][0]) == _state(run[0]):
            merged[-1].extend(run)
        else:
            merged.append(run)
    return merged


def _pct(before: int | None, after: int | None) -> tuple[int, float] | None:
    if before is None or after is None or before <= 0:
        return None
    return after - before, (after - before) / before * 100


def _boundary_steps(rows: list[FirstTurn], min_pct: float) -> list[Step]:
    steps = []
    runs = _runs(rows)
    for prev, run in pairwise(runs):
        at = run[0].at
        before_rows = [r for r in rows if at - timedelta(days=BASELINE_DAYS) <= r.at < at]
        before, after = window(before_rows), window(run)
        change = _pct(before.total, after.total)
        if change is None or abs(change[1]) < min_pct:
            continue
        kind = "config" if _state(prev[0])[0] != _state(run[0])[0] else "version"
        steps.append(Step(at=at, kind=kind, model=after.model, role=run[0].cell, before=before, after=after, delta=change[0], pct=change[1]))
    return steps


def _day_steps(rows: list[FirstTurn], min_pct: float, boundaries: list[Step]) -> list[Step]:
    steps: list[Step] = []
    days = sorted({r.at.date() for r in rows})
    flagged_prev = False
    for day in days:
        start = datetime.combine(day, datetime.min.time(), tzinfo=rows[0].at.tzinfo)
        end = start + timedelta(days=1)
        day_rows = [r for r in rows if start <= r.at < end]
        base_rows = [r for r in rows if start - timedelta(days=BASELINE_DAYS) <= r.at < start]
        near_boundary = any(start <= b.at < end + timedelta(days=1) for b in boundaries)
        if len(day_rows) < MIN_DAY or len(base_rows) < MIN_BASELINE or near_boundary:
            flagged_prev = False
            continue
        before, after = window(base_rows), window(day_rows)
        change = _pct(before.total, after.total)
        hit = change is not None and abs(change[1]) >= min_pct
        if hit and not flagged_prev and change is not None:
            steps.append(Step(at=start, kind="day", model=after.model, role=day_rows[0].cell, before=before, after=after,
                              delta=change[0], pct=change[1]))
        flagged_prev = hit
    return steps


def find_steps(rows: list[FirstTurn], min_pct: float) -> list[Step]:
    """Steps of one cell's rows, oldest first. Rows are compared only within one model and one role."""
    parts: dict[tuple[str | None, str], list[FirstTurn]] = {}
    for row in sorted(rows, key=lambda r: r.at):
        parts.setdefault((row.model, row.cell), []).append(row)
    steps: list[Step] = []
    for part_rows in parts.values():
        boundaries = _boundary_steps(part_rows, min_pct)
        steps += boundaries + _day_steps(part_rows, min_pct, boundaries)
    steps.sort(key=lambda s: s.at)
    return steps


def in_cell(role: str, launch_mode: str | None, work_role: str | None) -> bool:
    """Whether a marker seen on (launch_mode, work_role) sessions belongs to the cell `role` (or the group "lane")."""
    mode = launch_mode or "project"
    group = ROLE_GROUPS.get(role)
    return group(mode, work_role) if group else cell_label(mode, work_role) == role
