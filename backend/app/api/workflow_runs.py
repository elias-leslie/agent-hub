"""Durable multi-model workflow runs.

POST /workflow-runs               create a run from a JSON definition (idempotent on request_id) and start it
GET  /workflow-runs               recent runs, newest first (paginated)
GET  /workflow-runs/{id}          run, steps, attempts (requested vs served model, outcome, usage, handoff)
POST /workflow-runs/{id}/resume   resolve a run paused for the owner (retry, skip or fail the waiting step)
POST /workflow-runs/{id}/cancel   stop the whole run (optional reason; who asked and when are kept)
POST /workflow-runs/{id}/steps/{key}/cancel   stop one step; the run carries on with its other steps
POST   /workflow-runs/{id}/steps        add steps (optional after / depends_on); reopens a completed run
PATCH  /workflow-runs/{id}/steps/{key}  change a pending step; 409 when it has started
DELETE /workflow-runs/{id}/steps/{key}  remove a pending step nothing depends on (or revise its dependents in the call)
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.access_control_constants import CLIENT_ID_HEADER, REQUEST_SOURCE_HEADER
from app.services.workflow_runs.engine import (
    WorkflowRunError,
    cancel_run,
    cancel_step,
    create_run,
    get_run_view,
    resume_run,
)
from app.services.workflow_runs.listing import list_runs
from app.services.workflow_runs.revisions import add_steps, remove_step, revise_step
from app.services.workflow_runs.schemas import (
    AddSteps,
    CancelRequest,
    OwnerDecision,
    RemoveStep,
    RunDefinition,
    StepRevision,
)

router = APIRouter(prefix="/workflow-runs", tags=["workflow-runs"])

_STATUS = {
    "not_found": 404,
    "step_not_found": 404,
    "already_finished": 409,
    "not_paused": 409,
    "no_such_step": 409,
    "unknown_agent": 422,
    "empty_chain": 422,
    "attempt_limit": 409,
    "blocked_dependencies": 409,
    "request_id_conflict": 409,
    "duplicate_step": 409,
    "step_not_pending": 409,
    "step_has_attempts": 409,
    "has_dependents": 409,
    "invalid_plan": 422,
}


def _http(error: WorkflowRunError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS.get(error.code, 400),
        # "error" and "details" are what the app-wide error handler passes on; the flat keys stay for in-process callers.
        detail={
            "code": error.code,
            "error": error.code,
            "message": str(error),
            "details": error.extra,
            **error.extra,
        },
    )


def _requester(request: Request) -> tuple[str | None, str | None]:
    """(client id, request source) of the caller, by the convention session requests use: header, else middleware state."""

    def pick(header: str, attr: str) -> str | None:
        for value in (request.headers.get(header), getattr(request.state, attr, None)):
            if isinstance(value, str) and value:
                return value
        return None

    return pick(CLIENT_ID_HEADER, "client_id"), pick(REQUEST_SOURCE_HEADER, "request_source")


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
    run_id: str,
    decision: OwnerDecision,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    client_id, source = _requester(request)
    try:
        result = await resume_run(
            db, run_id, decision, requested_by=client_id, request_source=source
        )
    except WorkflowRunError as error:
        raise _http(error) from error
    if result["state"] == "running":
        await _enqueue(run_id)
    return result


@router.post("/{run_id}/cancel")
async def cancel_workflow_run(
    run_id: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    body: CancelRequest | None = None,
) -> dict[str, Any]:
    client_id, source = _requester(request)
    try:
        result = await cancel_run(
            db, run_id, body or CancelRequest(), requested_by=client_id, request_source=source
        )
    except WorkflowRunError as error:
        raise _http(error) from error
    return result


@router.post("/{run_id}/steps/{step_key}/cancel")
async def cancel_workflow_step(
    run_id: str,
    step_key: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    body: CancelRequest | None = None,
) -> dict[str, Any]:
    client_id, source = _requester(request)
    try:
        result = await cancel_step(
            db, run_id, step_key, body or CancelRequest(), requested_by=client_id, request_source=source
        )
    except WorkflowRunError as error:
        raise _http(error) from error
    if result["state"] == "running" and not result["cancelling"]:
        await _enqueue(run_id)  # the cancelled step may have been the last thing the run waited for
    return result


@router.post("/{run_id}/steps")
async def add_workflow_steps(
    run_id: str,
    body: AddSteps,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    client_id, source = _requester(request)
    try:
        result = await add_steps(db, run_id, body, requested_by=client_id, request_source=source)
    except WorkflowRunError as error:
        raise _http(error) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return await _after_revision(db, run_id, result)


@router.patch("/{run_id}/steps/{step_key}")
async def revise_workflow_step(
    run_id: str,
    step_key: str,
    body: StepRevision,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    client_id, source = _requester(request)
    try:
        result = await revise_step(
            db, run_id, step_key, body, requested_by=client_id, request_source=source
        )
    except WorkflowRunError as error:
        raise _http(error) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return await _after_revision(db, run_id, result)


@router.delete("/{run_id}/steps/{step_key}")
async def remove_workflow_step(
    run_id: str,
    step_key: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    body: RemoveStep | None = None,
) -> dict[str, Any]:
    client_id, source = _requester(request)
    try:
        result = await remove_step(
            db, run_id, step_key, body, requested_by=client_id, request_source=source
        )
    except WorkflowRunError as error:
        raise _http(error) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return await _after_revision(db, run_id, result)


async def _after_revision(db: AsyncSession, run_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """Queue an advance when the change left the run with work and nothing running, then return the run view."""

    enqueue = result.pop("enqueue", False)
    if enqueue:
        await _enqueue(run_id)
    view = await get_run_view(db, run_id)
    return {**result, "run": view}
