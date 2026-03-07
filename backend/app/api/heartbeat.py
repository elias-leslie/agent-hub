"""Heartbeat trigger and status API endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.workflows._heartbeat_redis import (
    get_heartbeat_metrics,
    get_heartbeat_running_info,
    get_last_run_info,
)
from app.workflows.persona_heartbeat import (
    HeartbeatInput,
    HeartbeatRuntimeInfo,
    check_project_permission,
    get_heartbeat_interval,
    get_heartbeat_runtime_info,
    persona_heartbeat_task,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/heartbeat", tags=["heartbeat"])


class HeartbeatStatusResponse(BaseModel):
    running: bool
    last_run: str | None = None
    elapsed_seconds: int | None = None
    interval_minutes: int
    # Last completed heartbeat metrics (from Redis)
    last_session_id: str | None = None
    last_turns: int | None = None
    last_tool_calls: int | None = None
    last_format_compliant: bool | None = None
    last_summary_stored: bool | None = None
    last_had_error: bool | None = None
    runtime: HeartbeatRuntimeInfo | None = None


class HeartbeatTriggerResponse(BaseModel):
    status: str
    message: str


@router.get("/status", response_model=HeartbeatStatusResponse)
async def heartbeat_status() -> HeartbeatStatusResponse:
    """Return current heartbeat running state, last run info, and metrics."""
    running_info = await get_heartbeat_running_info()
    last_run = await get_last_run_info()
    interval_minutes, _ = await get_heartbeat_interval()
    metrics = await get_heartbeat_metrics()
    runtime = await get_heartbeat_runtime_info()

    resp = HeartbeatStatusResponse(
        running=running_info is not None,
        last_run=last_run,
        elapsed_seconds=running_info.get("elapsed_seconds") if running_info else None,
        interval_minutes=interval_minutes,
        runtime=runtime,
    )

    if metrics:
        resp.last_session_id = metrics.get("session_id")
        resp.last_turns = int(metrics["turns"]) if metrics.get("turns") else None
        resp.last_tool_calls = int(metrics["tool_calls"]) if metrics.get("tool_calls") else None
        resp.last_format_compliant = metrics.get("format_compliant") == "True"
        resp.last_summary_stored = metrics.get("summary_stored") == "True"
        resp.last_had_error = metrics.get("had_error") == "True"

    return resp


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
    _, onboarding_complete = await get_heartbeat_interval()
    if not onboarding_complete:
        raise HTTPException(status_code=400, detail="Persona onboarding not complete")

    # Check project permissions
    if not await check_project_permission():
        raise HTTPException(status_code=403, detail="Heartbeat project permission is off")

    # Dispatch via Hatchet (fire-and-forget)
    persona_heartbeat_task.run_no_wait(HeartbeatInput(manual=True))
    logger.info("Manual heartbeat triggered via API")

    return HeartbeatTriggerResponse(status="dispatched", message="Heartbeat triggered")
