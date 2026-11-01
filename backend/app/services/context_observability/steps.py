"""Step finder: where a cell's first-turn size moved by at least jump_pct, and what changed there.

A cell is one (harness, role) of the Cost matrix. Rows are split by model first, so a day of Haiku lanes is never read
as a drop in Opus lanes. Two detectors, each needing at least 5 starts on both sides (MIN_AFTER, MIN_DAY, MIN_BASELINE):
  - a boundary step: the config fingerprint or the harness version changed and stayed (at least MIN_AFTER starts), so
    the size before it (the 7 days up to it) is compared with the size after;
  - a day step: a day's median (at least MIN_DAY starts) against the 7 days before it, for growth no marker explains.
The move is judged on the first turn without the brief (a pasted brief is not a context change); a step's `delta` and
`pct` are still the totals, and `pct_body` is what was judged. `markers` on a step are filled by the caller (they need
the database and git).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from itertools import pairwise

from .baseline import FirstTurn, cell_label, med
from .markers import Marker

BASELINE_DAYS = 7
MIN_AFTER = 5  # starts a new fingerprint or version needs to count as a change that stayed
MIN_DAY = 5  # starts a day needs to have a median of its own
MIN_BASELINE = 5  # starts the side before a step needs

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
    body: int | None = None  # total without the brief (None: no start with a known brief)


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
    pct_body: float | None = None  # the move without the brief: what decided that this is a step


@dataclass
class Found:
    """A step with the starts on either side of it: the one before/after every view (Trend, `why`, Cell) explains."""

    step: Step
    before_rows: list[FirstTurn]
    after_rows: list[FirstTurn]


@dataclass(frozen=True)
class Dip:
    """A day whose median moved by jump_pct or more against the week before but is not a step, and why not."""

    day: date
    total: int | None
    before_total: int | None
    pct: float
    n_day: int
    n_before: int
    reason: str


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
        body=med(None if r.brief_tokens is None else r.total - r.brief_tokens for r in rows),
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


def _judge(before: Window, after: Window, min_pct: float) -> tuple[tuple[int, float], float] | None:
    """(total delta and pct, pct without the brief) when the move without the brief is at least min_pct, else None."""
    body, total = _pct(before.body, after.body), _pct(before.total, after.total)
    if body is None or total is None or abs(body[1]) < min_pct:
        return None
    return total, body[1]


def _state_change(prev: FirstTurn, row: FirstTurn) -> str | None:
    """"config" or "version" when both sides know the value and it differs; an unknown value is not a change."""
    if prev.config_fp and row.config_fp and prev.config_fp != row.config_fp:
        return "config"
    if prev.version and row.version and prev.version != row.version:
        return "version"
    return None


def _boundary_steps(rows: list[FirstTurn], min_pct: float) -> list[Found]:
    """A state that stayed and was not already running: sessions of two kinds that interleave in one cell (another
    harness version still open, another tool set) swap places run after run, and only the first sighting counts."""
    found = []
    for prev, run in pairwise(_runs(rows)):
        at = run[0].at
        kind = _state_change(prev[0], run[0])
        before_rows = [r for r in rows if at - timedelta(days=BASELINE_DAYS) <= r.at < at]
        if kind is None or len(before_rows) < MIN_BASELINE:
            continue
        if sum(1 for r in before_rows if _state(r) == _state(run[0])) >= MIN_AFTER:
            continue  # this state was already running in the week before: sessions of two kinds side by side, not a change
        before, after = window(before_rows), window(run)
        judged = _judge(before, after, min_pct)
        if judged is None:
            continue
        change, pct_body = judged
        found.append(Found(Step(at=at, kind=kind, model=after.model, role=run[0].cell, before=before, after=after, delta=change[0],
                                pct=change[1], pct_body=pct_body), before_rows, list(run)))
    return found


def _day_steps(rows: list[FirstTurn], min_pct: float, boundaries: list[Found]) -> list[Found]:
    found: list[Found] = []
    days = sorted({r.at.date() for r in rows})
    flagged_prev = False
    for day in days:
        start = datetime.combine(day, datetime.min.time(), tzinfo=rows[0].at.tzinfo)
        end = start + timedelta(days=1)
        day_rows = [r for r in rows if start <= r.at < end]
        base_rows = [r for r in rows if start - timedelta(days=BASELINE_DAYS) <= r.at < start]
        near_boundary = any(start <= b.step.at < end + timedelta(days=1) for b in boundaries)
        if len(day_rows) < MIN_DAY or len(base_rows) < MIN_BASELINE or near_boundary:
            flagged_prev = False
            continue
        before, after = window(base_rows), window(day_rows)
        judged = _judge(before, after, min_pct)
        if judged is not None and not flagged_prev:
            change, pct_body = judged
            found.append(Found(Step(at=start, kind="day", model=after.model, role=day_rows[0].cell, before=before, after=after,
                                    delta=change[0], pct=change[1], pct_body=pct_body), base_rows, day_rows))
        flagged_prev = judged is not None
    return found


def find_step_rows(rows: list[FirstTurn], min_pct: float) -> list[Found]:
    """Steps of one cell's rows, oldest first, each with its before and after starts. Rows are compared only within one
    model and one role."""
    parts: dict[tuple[str | None, str], list[FirstTurn]] = {}
    for row in sorted(rows, key=lambda r: r.at):
        parts.setdefault((row.model, row.cell), []).append(row)
    found: list[Found] = []
    for part_rows in parts.values():
        boundaries = _boundary_steps(part_rows, min_pct)
        found += boundaries + _day_steps(part_rows, min_pct, boundaries)
    found.sort(key=lambda f: f.step.at)
    return found


def find_steps(rows: list[FirstTurn], min_pct: float) -> list[Step]:
    """Steps of one cell's rows, oldest first (see find_step_rows)."""
    return [f.step for f in find_step_rows(rows, min_pct)]


def find_dips(rows: list[FirstTurn], min_pct: float, found: list[Found]) -> list[Dip]:
    """Days where the cell's daily median (all its starts together, as the Trend chart draws it) is min_pct or more
    away from the week before but the step finder did not flag: the same rule, with the reason it did not apply."""
    ordered = sorted(rows, key=lambda r: r.at)
    stepped = {f.step.at.date() for f in found if f.step.kind == "day"}
    dips = []
    for day in sorted({r.at.date() for r in ordered}):
        start = datetime.combine(day, datetime.min.time(), tzinfo=ordered[0].at.tzinfo)
        day_rows = [r for r in ordered if start <= r.at < start + timedelta(days=1)]
        base_rows = [r for r in ordered if start - timedelta(days=BASELINE_DAYS) <= r.at < start]
        after, before = window(day_rows), window(base_rows)
        move = _pct(before.total, after.total)
        if move is None or abs(move[1]) < min_pct or day in stepped:
            continue
        if any(f.step.at.date() in (day, day - timedelta(days=1)) for f in found) or (dips and dips[-1].day == day - timedelta(days=1)):
            continue  # a step of its own explains this day, or it is the return from the dip before
        if len(day_rows) < MIN_DAY:
            reason = f"only {len(day_rows)} start{'s' if len(day_rows) != 1 else ''} that day; a step needs {MIN_DAY}"
        elif len(base_rows) < MIN_BASELINE:
            reason = f"only {len(base_rows)} start{'s' if len(base_rows) != 1 else ''} in the week before; a step needs {MIN_BASELINE}"
        else:
            reason = f"starts are compared per model and role, and none had {MIN_DAY} that day and {MIN_BASELINE} in the week before"
        mix = Counter(r.model.removeprefix("claude-") for r in day_rows if r.model).most_common()
        if len(mix) > 1:
            reason += "; that day mixes models (" + ", ".join(f"{m} {n}" for m, n in mix[:3]) + ") and steps compare one model at a time"
        dips.append(Dip(day=day, total=after.total, before_total=before.total, pct=move[1], n_day=len(day_rows), n_before=len(base_rows),
                        reason=reason))
    return dips


def in_cell(role: str, launch_mode: str | None, work_role: str | None) -> bool:
    """Whether a marker seen on (launch_mode, work_role) sessions belongs to the cell `role` (or the group "lane")."""
    mode = launch_mode or "project"
    group = ROLE_GROUPS.get(role)
    return group(mode, work_role) if group else cell_label(mode, work_role) == role
