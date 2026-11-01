"""Context policy rows: budgets (warn level per harness x role, one global jump) and config knobs.

Both are data the owner edits (`context_budgets`, `context_knobs`), never constants here.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContextBudget, ContextKnob

ANY = "*"


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
        """The most specific row: (harness, role), then (harness, *), then (*, role), then (*, *)."""
        by_key = {(b.harness, b.role): b for b in self.budgets}
        for key in ((harness, role), (harness, ANY), (ANY, role), (ANY, ANY)):
            if key in by_key:
                return by_key[key]
        return None

    def knobs_for(self, harness: str, role: str) -> list[Knob]:
        return [k for k in self.knobs if k.harness in (ANY, harness) and k.role in (ANY, role)]


async def load_policy(db: AsyncSession) -> Policy:
    rows = (await db.execute(select(ContextBudget))).scalars().all()
    jump = next((r.jump_pct for r in rows if r.harness == ANY and r.role == ANY and r.jump_pct is not None), None)
    knobs = (await db.execute(select(ContextKnob).order_by(ContextKnob.name))).scalars().all()
    return Policy(
        budgets=tuple(Budget(r.harness, r.role, int(r.warn_tokens)) for r in rows),
        jump_pct=jump,
        knobs=tuple(Knob(k.name, k.harness, k.role, k.repo_path, k.file_path, k.note) for k in knobs),
    )
