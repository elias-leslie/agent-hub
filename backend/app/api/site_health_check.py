"""Site health check trigger API — dispatches single-project checks post-merge."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from app.workflows.site_health_check import (
    FRONTEND_PORTS,
    SingleProjectCheckInput,
    single_project_health_check_task,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/site-health-check", tags=["site-health-check"])


class TriggerRequest(BaseModel):
    project_id: str
    task_id: str | None = None


class TriggerResponse(BaseModel):
    status: str
    project_id: str
    message: str | None = None


@router.post("/trigger", response_model=TriggerResponse)
async def trigger_site_health_check(request: TriggerRequest) -> TriggerResponse:
    """Trigger an async site health check for a single project.

    Called by `st done` after merging a task with frontend changes.
    Dispatches a Hatchet task (fire-and-forget) and returns immediately.
    """
    if request.project_id not in FRONTEND_PORTS:
        return TriggerResponse(
            status="skipped",
            project_id=request.project_id,
            message=f"Unknown project: {request.project_id}",
        )

    check_input = SingleProjectCheckInput(
        project_id=request.project_id,
        task_id=request.task_id,
    )
    await single_project_health_check_task.aio_run_no_wait(input=check_input)

    logger.info(
        "Dispatched site health check for %s (task: %s)",
        request.project_id,
        request.task_id,
    )
    return TriggerResponse(
        status="dispatched",
        project_id=request.project_id,
    )
