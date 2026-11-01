"""Context observability read side: why a cell moved, its steps and markers, and the budget policy rows.

Observability only: nothing here blocks a launch or a write. Budgets are rows the owner edits.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import ContextBudget
from app.services.api_key_auth import AuthenticatedKey, require_api_key
from app.services.context_observability import markers as marker_service
from app.services.context_observability import why as why_service
from app.services.context_observability.budgets import CellState, cell_states
from app.services.context_observability.markers import Marker
from app.services.context_observability.steps import Step
from app.services.context_observability.why import Why

router = APIRouter(prefix="/context-observability", tags=["context-observability"])
DB = Annotated[AsyncSession, Depends(get_db)]
Auth = Annotated[AuthenticatedKey | None, Depends(require_api_key)]
Harness = Annotated[str, Query(min_length=1, max_length=20)]
Role = Annotated[str, Query(min_length=1, max_length=80, description="A Cost-matrix cell, or 'lane' for every launched non-coordinator role")]


class BudgetRow(BaseModel):
    harness: str
    role: str
    warn_tokens: int
    jump_pct: int | None
    note: str | None
    updated_at: datetime | None


class BudgetWrite(BaseModel):
    harness: str = Field(min_length=1, max_length=20)
    role: str = Field(min_length=1, max_length=80)
    warn_tokens: int = Field(gt=0)
    note: str | None = None


class JumpWrite(BaseModel):
    jump_pct: int = Field(gt=0, le=1000)


@router.get("/why", response_model=Why)
async def get_why(
    db: DB, harness: Harness, role: Role, auth: Auth = None,
    at: Annotated[datetime | None, Query(description="Explain the move at this time; default the newest step")] = None,
) -> Why:
    """What moved this cell's first turn: harness version, config knob, what Agent Hub delivers, the brief or the model."""
    return await why_service.why(db, harness, role, at=at)


@router.get("/steps", response_model=list[Step])
async def get_steps(db: DB, harness: Harness, role: Role, auth: Auth = None, days: Annotated[int, Query(ge=1, le=90)] = 30) -> list[Step]:
    """Moves of at least the global jump_pct in this cell, with the markers between the starts either side."""
    return await why_service.steps_with_markers(db, harness, role, days=days)


@router.get("/markers", response_model=list[Marker])
async def get_markers(
    db: DB, auth: Auth = None, harness: Annotated[str | None, Query(max_length=20)] = None,
    start: datetime | None = None, end: datetime | None = None,
) -> list[Marker]:
    """Revisions of delivered memories and prompts, harness versions, config changes and placement changes, oldest first."""
    stop = end or datetime.now(UTC)
    return await marker_service.view_markers(db, start or stop - timedelta(days=30), stop, harness=harness)


@router.get("/budget-state", response_model=list[CellState])
async def get_budget_state(db: DB, auth: Auth = None) -> list[CellState]:
    """Every cell's last-24 h median against its budget row and the week before; `reason` is set when it is over."""
    return await cell_states(db)


@router.get("/budgets", response_model=list[BudgetRow])
async def list_budgets(db: DB, auth: Auth = None) -> list[BudgetRow]:
    rows = (await db.execute(select(ContextBudget).order_by(ContextBudget.harness, ContextBudget.role))).scalars().all()
    return [BudgetRow(harness=r.harness, role=r.role, warn_tokens=r.warn_tokens, jump_pct=r.jump_pct, note=r.note,
                      updated_at=r.updated_at) for r in rows]


@router.put("/budgets", response_model=BudgetRow)
async def put_budget(body: BudgetWrite, db: DB, auth: Auth = None) -> BudgetRow:
    """Set the warn level of one (harness or '*', role or '*') cell."""
    stmt = pg_insert(ContextBudget).values(harness=body.harness, role=body.role, warn_tokens=body.warn_tokens, note=body.note)
    await db.execute(stmt.on_conflict_do_update(
        index_elements=["harness", "role"], set_={"warn_tokens": stmt.excluded.warn_tokens, "note": stmt.excluded.note}))
    await db.commit()
    row = (await db.execute(select(ContextBudget).where(ContextBudget.harness == body.harness, ContextBudget.role == body.role))).scalar_one()
    await db.refresh(row)
    return BudgetRow(harness=row.harness, role=row.role, warn_tokens=row.warn_tokens, jump_pct=row.jump_pct, note=row.note,
                     updated_at=row.updated_at)


@router.put("/budgets/jump", response_model=BudgetRow)
async def put_jump(body: JumpWrite, db: DB, auth: Auth = None) -> BudgetRow:
    """Set the one global step threshold (percent), kept on the ('*', '*') row."""
    row = (await db.execute(select(ContextBudget).where(ContextBudget.harness == "*", ContextBudget.role == "*"))).scalar_one_or_none()
    if row is None:
        raise HTTPException(409, "The ('*', '*') budget row is missing; set it with PUT /budgets first")
    row.jump_pct = body.jump_pct
    await db.commit()
    await db.refresh(row)
    return BudgetRow(harness=row.harness, role=row.role, warn_tokens=row.warn_tokens, jump_pct=row.jump_pct, note=row.note,
                     updated_at=row.updated_at)


@router.delete("/budgets", status_code=204)
async def delete_budget(db: DB, harness: Harness, role: Role, auth: Auth = None) -> None:
    """Remove a cell's own row so the next most specific one applies. The ('*', '*') row stays."""
    if harness == "*" and role == "*":
        raise HTTPException(409, "The ('*', '*') row holds the global jump_pct and the fallback level; edit it instead")
    await db.execute(delete(ContextBudget).where(ContextBudget.harness == harness, ContextBudget.role == role))
    await db.commit()
