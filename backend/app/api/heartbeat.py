"""Heartbeat trigger and status API endpoints."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.db import async_session
from app.models.session import Session
from app.workflows._heartbeat_redis import (
    HeartbeatRunningInfo,
    clear_heartbeat_running,
    get_heartbeat_metrics,
    get_heartbeat_running_info,
    get_last_run_info,
)
from app.workflows.persona_heartbeat import (
    HEARTBEAT_PROJECT,
    HeartbeatInput,
    HeartbeatRuntimeInfo,
    check_project_permission,
    get_heartbeat_interval,
    get_heartbeat_runtime_info,
    get_persona_execution_state,
    persona_heartbeat_task,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/heartbeat", tags=["heartbeat"])

_HEARTBEAT_SESSION_GRACE_SECONDS = 60
_HEARTBEAT_SESSION_IDLE_SECONDS = 180


class HeartbeatStatusResponse(BaseModel):
    running: bool
    last_run: str | None = None
    elapsed_seconds: int | None = None
    interval_minutes: int
    execution_state: str = "active"
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


class HeartbeatTriggerRequest(BaseModel):
    target_project_id: str | None = None


async def _has_live_heartbeat_session(started_at_iso: str) -> bool:
    """Sanity-check the Redis running lock against recent persona session activity."""
    started_at = datetime.fromisoformat(started_at_iso)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    now = datetime.now(UTC)

    async with async_session() as db:
        result = await db.execute(
            select(Session.updated_at)
            .where(
                Session.agent_slug == "persona",
                Session.created_at >= started_at - timedelta(seconds=30),
            )
            .order_by(Session.updated_at.desc())
            .limit(1)
        )
        last_updated = result.scalar_one_or_none()

    if last_updated is None:
        return (now - started_at).total_seconds() <= _HEARTBEAT_SESSION_GRACE_SECONDS

    if last_updated.tzinfo is None:
        last_updated = last_updated.replace(tzinfo=UTC)
    return (now - last_updated).total_seconds() <= _HEARTBEAT_SESSION_IDLE_SECONDS


async def _get_effective_running_info() -> HeartbeatRunningInfo | None:
    """Return live running info, clearing stale heartbeat locks when necessary."""
    running_info = await get_heartbeat_running_info()
    if not running_info:
        return None
    if await _has_live_heartbeat_session(str(running_info["started_at"])):
        return running_info

    logger.warning(
        "Clearing stale heartbeat running lock (started_at=%s)",
        running_info["started_at"],
    )
    await clear_heartbeat_running()
    return None


@router.get("/status", response_model=HeartbeatStatusResponse)
async def heartbeat_status() -> HeartbeatStatusResponse:
    """Return current heartbeat running state, last run info, and metrics."""
    running_info = await _get_effective_running_info()
    last_run = await get_last_run_info()
    interval_minutes, _ = await get_heartbeat_interval()
    execution_state = await get_persona_execution_state()
    metrics = await get_heartbeat_metrics()
    runtime = await get_heartbeat_runtime_info()

    resp = HeartbeatStatusResponse(
        running=running_info is not None,
        last_run=last_run,
        elapsed_seconds=running_info.get("elapsed_seconds") if running_info else None,
        interval_minutes=interval_minutes,
        execution_state=execution_state,
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
async def heartbeat_trigger(request: HeartbeatTriggerRequest | None = None) -> HeartbeatTriggerResponse:
    """Manually trigger a heartbeat. Returns 409 if already running."""
    from app.constants import VALID_PROJECT_IDS

    target_project_id = request.target_project_id if request else None
    if target_project_id and target_project_id not in VALID_PROJECT_IDS:
        raise HTTPException(status_code=400, detail=f"Unknown target project: {target_project_id}")

    # Check if already running
    running_info = await _get_effective_running_info()
    if running_info:
        raise HTTPException(
            status_code=409,
            detail=f"Heartbeat already in progress (started {running_info['elapsed_seconds']}s ago)",
        )

    # Check onboarding
    _, onboarding_complete = await get_heartbeat_interval()
    if not onboarding_complete:
        raise HTTPException(status_code=400, detail="Persona onboarding not complete")
    if await get_persona_execution_state() == "paused":
        raise HTTPException(status_code=409, detail="Jenny is paused")

    # Check project permissions
    permission_project = target_project_id or HEARTBEAT_PROJECT
    if not await check_project_permission(permission_project):
        raise HTTPException(status_code=403, detail=f"Heartbeat project permission is off for {permission_project}")

    # Dispatch via Hatchet (fire-and-forget)
    persona_heartbeat_task.run_no_wait(
        HeartbeatInput(manual=True, target_project_id=target_project_id)
    )
    logger.info("Manual heartbeat triggered via API for target=%s", target_project_id or "persona-sandbox")

    if target_project_id:
        return HeartbeatTriggerResponse(
            status="dispatched",
            message=f"Heartbeat triggered for {target_project_id}",
        )
    return HeartbeatTriggerResponse(status="dispatched", message="Heartbeat triggered")
