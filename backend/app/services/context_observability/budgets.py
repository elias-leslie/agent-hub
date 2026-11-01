"""Budget state per cell: is a harness x role over its warn level, or did it jump?

A cell is over when its median first turn of the last 24 h (at least MIN_RECENT starts) is above its warn_tokens row,
or at least jump_pct above the median of the 7 days before (same model, at least MIN_JUMP starts on each side). The jump
compares the first turn without the brief, so a long pasted brief does not move it, and uses only starts whose brief is
known. A drop is never over.

`reason` is the raw trigger, recomputed from the data each pass. A cell that was over does not clear on the same line:
`warn_clear` is true below WARN_CLEAR of the warn level and `jump_clear` below half of jump_pct; false inside that band;
None when there is too little data to say (the caller then keeps the state it had).
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
MIN_RECENT = 3  # starts for the warn level
MIN_JUMP = 5  # starts on each side of a jump
WARN_CLEAR = 0.9  # an open warn clears below this share of its level
JUMP_CLEAR = 0.5  # an open jump clears below this share of jump_pct


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
    pct: float | None  # recent against baseline, same model, without the brief
    reason: str | None  # warn | jump | None
    warn_clear: bool | None = None  # an open warn may clear: under WARN_CLEAR of its level (None: too little data)
    jump_clear: bool | None = None  # an open jump may clear: under JUMP_CLEAR of jump_pct (None: too little data)


def _body(row: FirstTurn) -> int | None:
    """The first turn without the brief (None: the brief is not known for this start)."""
    return None if row.brief_tokens is None else row.total - row.brief_tokens


def _state(harness: str, cell: str, rows: list[FirstTurn], policy: Policy, now: datetime) -> CellState:
    edge = now - timedelta(hours=RECENT_HOURS)
    recent = [r for r in rows if r.at >= edge]
    model = Counter(r.model for r in recent).most_common(1)[0][0] if recent else None
    base_same = [r for r in rows if r.at < edge and r.model == model and _body(r) is not None]
    recent_same = [r for r in recent if r.model == model and _body(r) is not None]
    budget = policy.budget_for(harness, cell)
    recent_med = med(r.total for r in recent)
    base_med = med(r.total for r in base_same)
    pct = None
    if len(recent_same) >= MIN_JUMP and len(base_same) >= MIN_JUMP:
        base_body, recent_body = med(_body(r) for r in base_same), med(_body(r) for r in recent_same)
        if base_body and recent_body is not None:
            pct = (recent_body - base_body) / base_body * 100
    enough = len(recent) >= MIN_RECENT and recent_med is not None
    reason = None
    if budget is not None and enough and recent_med is not None and recent_med > budget.warn_tokens:
        reason = "warn"
    elif pct is not None and policy.jump_pct is not None and pct >= policy.jump_pct:
        reason = "jump"
    warn_clear = None
    if enough and recent_med is not None:
        warn_clear = budget is None or recent_med <= budget.warn_tokens * WARN_CLEAR
    jump_clear = True if policy.jump_pct is None else (None if pct is None else pct < policy.jump_pct * JUMP_CLEAR)
    return CellState(harness=harness, cell=cell, n_recent=len(recent), recent=recent_med, n_baseline=len(base_same),
                     baseline=base_med, warn_tokens=budget.warn_tokens if budget else None, jump_pct=policy.jump_pct,
                     pct=pct, reason=reason, warn_clear=warn_clear, jump_clear=jump_clear)


async def cell_states(db: AsyncSession, *, now: datetime | None = None, policy: Policy | None = None) -> list[CellState]:
    now = now or datetime.now(UTC)
    policy = policy or await load_policy(db)
    rows = await load_first_turns(db, since=now - timedelta(hours=RECENT_HOURS, days=BASELINE_DAYS), until=now)
    cells: dict[tuple[str, str], list[FirstTurn]] = defaultdict(list)
    for row in rows:
        cells[(row.harness, row.cell)].append(row)
    return [_state(h, c, items, policy, now) for (h, c), items in sorted(cells.items())]
