"""Context policy rows: budgets (warn level per harness x role, one global jump) and config knobs.

Both are data the owner edits (`context_budgets`, `context_knobs`), never constants here.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContextBudget, ContextKnob

ANY = "*"
LANE = "lane"  # the owner's word for any launched project session that is not the coordinator (steps.ROLE_GROUPS)
_NOT_LANE = ("blank", "coordinator", "exec:coordinator", "unknown")


def is_lane_cell(cell: str) -> bool:
    """Whether a Cost-matrix cell label is a lane (a launched role): not the coordinator, a blank or sub-agent session,
    or one with no role. The same set as steps.ROLE_GROUPS["lane"], which works from the launch mode and role."""
    return cell == LANE or not (cell in _NOT_LANE or cell.startswith(("subagent:", "agent:")))


def _roles(role: str) -> list[str]:
    """A cell's own label first, then the group it belongs to."""
    return [role, LANE] if role != LANE and is_lane_cell(role) else [role]


@dataclass(frozen=True)
class Budget:
    harness: str
    role: str
    warn_tokens: int


@dataclass(frozen=True)
class Knob:
    name: str
    harness: str
    role: str
    repo_path: str
    file_path: str
    note: str | None


@dataclass(frozen=True)
class Policy:
    budgets: tuple[Budget, ...]
    jump_pct: int | None  # None: no global jump row, so steps are not flagged
    knobs: tuple[Knob, ...]

    def budget_for(self, harness: str, role: str) -> Budget | None:
        """The most specific row: (harness, role), then (*, role), then (harness, *), then (*, *). A role row beats a
        harness row, so a (*, coordinator) row the owner adds applies to every harness that has no coordinator row of
        its own. A "lane" row covers every lane cell; the cell's own row comes first."""
        by_key = {(b.harness, b.role): b for b in self.budgets}
        roles = _roles(role)
        for key in (*((harness, r) for r in roles), *((ANY, r) for r in roles), (harness, ANY), (ANY, ANY)):
            if key in by_key:
                return by_key[key]
        return None

    def knobs_for(self, harness: str, role: str) -> list[Knob]:
        """Knobs registered for this harness and cell (or the "lane" group, which a lane cell belongs to)."""
        roles = {ANY, *_roles(role)}
        return [k for k in self.knobs if k.harness in (ANY, harness) and k.role in roles]


async def load_policy(db: AsyncSession) -> Policy:
    rows = (await db.execute(select(ContextBudget))).scalars().all()
    jump = next((r.jump_pct for r in rows if r.harness == ANY and r.role == ANY and r.jump_pct is not None), None)
    knobs = (await db.execute(select(ContextKnob).order_by(ContextKnob.name))).scalars().all()
    return Policy(
        budgets=tuple(Budget(r.harness, r.role, int(r.warn_tokens)) for r in rows),
        jump_pct=jump,
        knobs=tuple(Knob(k.name, k.harness, k.role, k.repo_path, k.file_path, k.note) for k in knobs),
    )
