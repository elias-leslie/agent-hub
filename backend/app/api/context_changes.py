"""Context change review: the queue of agent context changes and the owner's keep / rework / refuse.

Agents keep writing context with no gate; these endpoints are for reviewing afterwards. A rework or refuse against
a target that changed since the reviewer loaded the queue returns 409 and changes nothing; reload and decide again.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.prompts import _invalidate_owned_agent_cache
from app.db import get_db
from app.models.context_change_review import ContextChangeReview
from app.services.api_key_auth import AuthenticatedKey, require_api_key
from app.services.context_changes import (
    DecideRequest,
    DecideResponse,
    Queue,
    ReviewConflict,
    ReworkRequest,
    Touched,
    build_queue,
    keep,
    refuse,
    rework,
)

router = APIRouter(prefix="/context-observability/changes", tags=["context-observability"])
DB = Annotated[AsyncSession, Depends(get_db)]
Auth = Annotated[AuthenticatedKey | None, Depends(require_api_key)]


class ReviewRecord(BaseModel):
    id: str
    target_kind: str
    target_id: str
    decision: str
    through_revision: str
    result_revision: str | None
    note: str | None
    by: str | None
    by_kind: str | None
    created_at: datetime


@router.get("", response_model=Queue)
async def list_changes(
    db: DB,
    auth: Auth = None,
    session: Annotated[str | None, Query(max_length=200, description="Only rows this writer session touched")] = None,
    kind: Annotated[Literal["memory", "prompt", "placement"] | None, Query()] = None,
) -> Queue:
    """Unreviewed changes, newest first, with diff, reach, writers, linked rows and the review agent's hint."""
    return await build_queue(db, session=session, kind=kind)


@router.get("/decisions", response_model=list[ReviewRecord])
async def list_decisions(
    db: DB,
    auth: Auth = None,
    decision: Annotated[Literal["keep", "rework", "refuse"] | None, Query()] = None,
    target_kind: Annotated[Literal["memory", "prompt", "placement"] | None, Query()] = None,
    target_id: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ReviewRecord]:
    """Past decisions (Kept, Reworked, Refused), newest first."""
    statement = select(ContextChangeReview).order_by(ContextChangeReview.created_at.desc()).limit(limit)
    if decision:
        statement = statement.where(ContextChangeReview.decision == decision)
    if target_kind:
        statement = statement.where(ContextChangeReview.target_kind == target_kind)
    if target_id:
        statement = statement.where(ContextChangeReview.target_id == target_id)
    rows = (await db.execute(statement)).scalars().all()
    return [ReviewRecord(id=str(r.id), target_kind=r.target_kind, target_id=r.target_id, decision=r.decision,
                         through_revision=r.through_revision, result_revision=r.result_revision, note=r.note,
                         by=r.by, by_kind=r.by_kind, created_at=r.created_at) for r in rows]


def _conflict(exc: ReviewConflict) -> HTTPException:
    return HTTPException(409, {"message": str(exc), "key": exc.key, "latest_revision": exc.latest_revision})


async def _finish(db: AsyncSession, touched: Touched) -> None:
    await db.commit()
    for prompt in touched.prompts:
        await _invalidate_owned_agent_cache(prompt)


@router.post("/keep", response_model=DecideResponse)
async def keep_changes(request: DecideRequest, db: DB, auth: Auth = None) -> DecideResponse:
    """Record a keep through each item's revision. Several items (e.g. all from one session) in one call."""
    result = await keep(db, request)
    await db.commit()
    return result


@router.post("/refuse", response_model=DecideResponse)
async def refuse_changes(request: DecideRequest, db: DB, auth: Auth = None) -> DecideResponse:
    """Undo each item's unreviewed changes, all or nothing: a create is archived, an update or delete restored."""
    touched = Touched()
    try:
        result = await refuse(db, request, touched)
    except ReviewConflict as exc:
        await db.rollback()
        raise _conflict(exc) from exc
    except HTTPException:
        await db.rollback()
        raise
    await _finish(db, touched)
    return result


@router.post("/rework", response_model=DecideResponse)
async def rework_change(request: ReworkRequest, db: DB, auth: Auth = None) -> DecideResponse:
    """Edit the target in place, or narrow it (project, role, or session-only = archived)."""
    touched = Touched()
    try:
        result = await rework(db, request, touched)
    except ReviewConflict as exc:
        await db.rollback()
        raise _conflict(exc) from exc
    except HTTPException:
        await db.rollback()
        raise
    await _finish(db, touched)
    return result
