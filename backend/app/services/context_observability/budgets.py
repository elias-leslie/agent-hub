"""Budget state per cell: is a harness x role over its warn level, or did it jump?

A cell is over when its median first turn of the last 24 h (at least MIN_RECENT starts) is above its warn_tokens row,
or at least jump_pct above the median of the 7 days before (same model, at least MIN_BASELINE starts). A drop is
never over. The state is recomputed from the data each pass, so it clears itself when the cell is back under.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from .baseline import FirstTurn, load_first_turns, med
from .policy import Policy, load_policy

RECENT_HOURS = 24
BASELINE_DAYS = 7
MIN_RECENT = 3
MIN_BASELINE = 5


@dataclass(frozen=True)
class CellState:
    harness: str
    cell: str
    n_recent: int
    recent: int | None
    n_baseline: int
    baseline: int | None
    warn_tokens: int | None
    jump_pct: int | None
    pct: float | None  # recent against baseline, same model
    reason: str | None  # warn | jump | None


def _state(harness: str, cell: str, rows: list[FirstTurn], policy: Policy, now: datetime) -> CellState:
    edge = now - timedelta(hours=RECENT_HOURS)
    recent = [r for r in rows if r.at >= edge]
    model = Counter(r.model for r in recent).most_common(1)[0][0] if recent else None
    base_same = [r for r in rows if r.at < edge and r.model == model]
    recent_same = [r for r in recent if r.model == model]
    budget = policy.budget_for(harness, cell)
    recent_med = med(r.total for r in recent)
    base_med = med(r.total for r in base_same)
    pct = None
    if recent_med is not None and base_med and len(recent_same) >= MIN_RECENT and len(base_same) >= MIN_BASELINE:
        same_med = med(r.total for r in recent_same)
        pct = None if same_med is None else (same_med - base_med) / base_med * 100
    reason = None
    if budget is not None and len(recent) >= MIN_RECENT and recent_med is not None and recent_med > budget.warn_tokens:
        reason = "warn"
    elif pct is not None and policy.jump_pct is not None and pct >= policy.jump_pct:
        reason = "jump"
    return CellState(harness=harness, cell=cell, n_recent=len(recent), recent=recent_med, n_baseline=len(base_same),
                     baseline=base_med, warn_tokens=budget.warn_tokens if budget else None, jump_pct=policy.jump_pct,
                     pct=pct, reason=reason)


async def cell_states(db: AsyncSession, *, now: datetime | None = None, policy: Policy | None = None) -> list[CellState]:
    now = now or datetime.now(UTC)
    policy = policy or await load_policy(db)
    rows = await load_first_turns(db, since=now - timedelta(hours=RECENT_HOURS, days=BASELINE_DAYS), until=now)
    cells: dict[tuple[str, str], list[FirstTurn]] = defaultdict(list)
    for row in rows:
        cells[(row.harness, row.cell)].append(row)
    return [_state(h, c, items, policy, now) for (h, c), items in sorted(cells.items())]
