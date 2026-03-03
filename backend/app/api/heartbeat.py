"""Heartbeat trigger and status API endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.workflows._heartbeat_redis import (
    get_heartbeat_running_info,
    get_last_run_info,
)
from app.workflows.persona_heartbeat import (
    HeartbeatInput,
    _check_project_permission,
    _get_heartbeat_interval,
    persona_heartbeat_task,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/heartbeat", tags=["heartbeat"])


class HeartbeatStatusResponse(BaseModel):
    running: bool
    last_run: str | None = None
    elapsed_seconds: int | None = None
    interval_minutes: int


class HeartbeatTriggerResponse(BaseModel):
    status: str
    message: str


@router.get("/status", response_model=HeartbeatStatusResponse)
async def heartbeat_status() -> HeartbeatStatusResponse:
    """Return current heartbeat running state and last run info."""
    running_info = await get_heartbeat_running_info()
    last_run = await get_last_run_info()
    interval_minutes, _ = await _get_heartbeat_interval()

    return HeartbeatStatusResponse(
        running=running_info is not None,
        last_run=last_run,
        elapsed_seconds=running_info["elapsed_seconds"] if running_info else None,
        interval_minutes=interval_minutes,
    )


@router.post("/trigger", response_model=HeartbeatTriggerResponse)
async def heartbeat_trigger() -> HeartbeatTriggerResponse:
    """Manually trigger a heartbeat. Returns 409 if already running."""
    # Check if already running
    running_info = await get_heartbeat_running_info()
    if running_info:
        raise HTTPException(
            status_code=409,
            detail=f"Heartbeat already in progress (started {running_info['elapsed_seconds']}s ago)",
        )

    # Check onboarding
    _, onboarding_complete = await _get_heartbeat_interval()
    if not onboarding_complete:
        raise HTTPException(status_code=400, detail="Persona onboarding not complete")

    # Check project permissions
    if not await _check_project_permission():
        raise HTTPException(status_code=403, detail="Heartbeat project permission is off")

    # Dispatch via Hatchet (fire-and-forget)
    persona_heartbeat_task.run_no_wait(HeartbeatInput(manual=True))
    logger.info("Manual heartbeat triggered via API")

    return HeartbeatTriggerResponse(status="dispatched", message="Heartbeat triggered")
