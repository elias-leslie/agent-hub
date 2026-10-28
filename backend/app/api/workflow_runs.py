"""Durable multi-model workflow runs.

POST /workflow-runs               create a run from a JSON definition (idempotent on request_id) and start it
GET  /workflow-runs               recent runs, newest first (paginated)
GET  /workflow-runs/{id}          run, steps, attempts (requested vs served model, outcome, usage, handoff)
POST /workflow-runs/{id}/resume   resolve a run paused for the owner (retry, skip or fail the waiting step)
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.workflow_runs.engine import WorkflowRunError, create_run, get_run_view, resume_run
from app.services.workflow_runs.listing import list_runs
from app.services.workflow_runs.schemas import OwnerDecision, RunDefinition

router = APIRouter(prefix="/workflow-runs", tags=["workflow-runs"])

_STATUS = {
    "not_found": 404,
    "not_paused": 409,
    "no_such_step": 409,
    "unknown_agent": 422,
    "empty_chain": 422,
    "attempt_limit": 409,
}


def _http(error: WorkflowRunError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS.get(error.code, 400), detail={"code": error.code, "message": str(error)}
    )


async def _enqueue(run_id: str) -> None:
    from app.workflows.workflow_run import enqueue_advance

    await enqueue_advance(run_id)


@router.post("", status_code=201)
async def create_workflow_run(
    definition: RunDefinition, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, Any]:
    try:
        run_id, created = await create_run(db, definition)
    except WorkflowRunError as error:
        raise _http(error) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if created:
        await _enqueue(run_id)
    view = await get_run_view(db, run_id)
    return {**(view or {}), "created": created}


@router.get("")
async def list_workflow_runs(
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    return await list_runs(db, limit=limit, offset=offset)


@router.get("/{run_id}")
async def get_workflow_run(
    run_id: str, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, Any]:
    view = await get_run_view(db, run_id)
    if view is None:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "run not found"}
        )
    return view


@router.post("/{run_id}/resume")
async def resume_workflow_run(
    run_id: str, decision: OwnerDecision, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, Any]:
    try:
        result = await resume_run(db, run_id, decision)
    except WorkflowRunError as error:
        raise _http(error) from error
    if result["state"] == "running":
        await _enqueue(run_id)
    return result
