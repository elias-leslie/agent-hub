"""Heartbeat trigger and status API endpoints."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.db import async_session
from app.models.session import Session
from app.services.workflow_schedule_registry import is_workflow_schedule_enabled
from app.workflows._heartbeat_redis import (
    HeartbeatRunningInfo,
    clear_heartbeat_running,
    get_heartbeat_metrics,
    get_heartbeat_running_info,
    get_heartbeat_state,
    get_last_run_info,
    record_heartbeat_attempt,
    record_heartbeat_skip,
    set_heartbeat_running,
)
from app.workflows.persona_heartbeat import (
    HEARTBEAT_PROJECT,
    HeartbeatInput,
    HeartbeatRuntimeInfo,
    check_project_permission,
    create_heartbeat_session_id,
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
    last_attempt: str | None = None
    last_success: str | None = None
    last_skip_reason: str | None = None
    last_error: str | None = None
    elapsed_seconds: int | None = None
    interval_minutes: int
    execution_state: str = "active"
    running_session_id: str | None = None
    running_owner_host: str | None = None
    running_owner_pid: int | None = None
    running_trigger: str | None = None
    running_project_id: str | None = None
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
    session_id: str | None = None


class HeartbeatTriggerRequest(BaseModel):
    target_project_id: str | None = None


async def _has_live_heartbeat_session(
    started_at_iso: str,
    session_id: str | None,
) -> bool:
    """Sanity-check the Redis running lock against the exact heartbeat session."""
    started_at = datetime.fromisoformat(started_at_iso)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    now = datetime.now(UTC)
    if not session_id:
        return (now - started_at).total_seconds() <= _HEARTBEAT_SESSION_GRACE_SECONDS

    async with async_session() as db:
        result = await db.execute(
            select(Session.updated_at)
            .where(
                Session.id == session_id,
                Session.agent_slug == "persona",
                Session.request_source == "heartbeat",
            )
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
    if await _has_live_heartbeat_session(
        str(running_info["started_at"]),
        running_info.get("session_id"),
    ):
        return running_info

    logger.warning(
        "Clearing stale heartbeat running lock (started_at=%s)",
        running_info["started_at"],
    )
    await clear_heartbeat_running(
        claim_token=running_info.get("claim_token"),
        session_id=running_info.get("session_id"),
    )
    return None


@router.get("/status", response_model=HeartbeatStatusResponse)
async def heartbeat_status() -> HeartbeatStatusResponse:
    """Return current heartbeat running state, last run info, and metrics."""
    running_info = await _get_effective_running_info()
    last_run = await get_last_run_info()
    state = await get_heartbeat_state()
    interval_minutes, _ = await get_heartbeat_interval()
    execution_state = await get_persona_execution_state()
    metrics = await get_heartbeat_metrics()
    runtime = await get_heartbeat_runtime_info()

    resp = HeartbeatStatusResponse(
        running=running_info is not None,
        last_run=last_run,
        last_attempt=state.get("last_attempt") if state else None,
        last_success=state.get("last_success") if state else last_run,
        last_skip_reason=state.get("last_skip_reason") if state else None,
        last_error=state.get("last_error") if state else None,
        elapsed_seconds=running_info.get("elapsed_seconds") if running_info else None,
        interval_minutes=interval_minutes,
        execution_state=execution_state,
        running_session_id=running_info.get("session_id") if running_info else None,
        running_owner_host=running_info.get("owner_host") if running_info else None,
        running_owner_pid=running_info.get("owner_pid") if running_info else None,
        running_trigger=running_info.get("trigger") if running_info else None,
        running_project_id=running_info.get("project_id") if running_info else None,
        runtime=runtime,
    )

    if metrics:
        resp.last_session_id = metrics.get("session_id") or (state.get("last_session_id") if state else None)
        resp.last_turns = int(metrics["turns"]) if metrics.get("turns") else None
        resp.last_tool_calls = int(metrics["tool_calls"]) if metrics.get("tool_calls") else None
        resp.last_format_compliant = metrics.get("format_compliant") == "True"
        resp.last_summary_stored = metrics.get("summary_stored") == "True"
        resp.last_had_error = metrics.get("had_error") == "True"
    elif state:
        resp.last_session_id = state.get("last_session_id")

    return resp


@router.post("/trigger", response_model=HeartbeatTriggerResponse)
async def heartbeat_trigger(
    request: HeartbeatTriggerRequest | None = None,
) -> HeartbeatTriggerResponse | JSONResponse:
    """Manually trigger a heartbeat. Returns 409 if already running."""
    from app.constants import VALID_PROJECT_IDS

    target_project_id = request.target_project_id if request else None
    if target_project_id and target_project_id not in VALID_PROJECT_IDS:
        raise HTTPException(status_code=400, detail=f"Unknown target project: {target_project_id}")

    # Check if already running
    running_info = await _get_effective_running_info()
    if running_info:
        return JSONResponse(
            status_code=409,
            content={
                "error": "http_error",
                "message": f"Heartbeat already in progress (started {running_info['elapsed_seconds']}s ago)",
                "running_session_id": running_info.get("session_id"),
            },
        )

    # Check onboarding
    _, onboarding_complete = await get_heartbeat_interval()
    if not onboarding_complete:
        raise HTTPException(status_code=400, detail="Persona onboarding not complete")
    if await get_persona_execution_state() == "paused":
        raise HTTPException(status_code=409, detail="Persona is paused")
    if not await is_workflow_schedule_enabled("persona_heartbeat"):
        await record_heartbeat_skip("schedule_disabled")
        logger.info("Manual heartbeat skipped via API because schedule is disabled")
        return HeartbeatTriggerResponse(
            status="skipped",
            message="Heartbeat skipped (schedule disabled)",
            session_id=None,
        )

    # Check project permissions
    permission_project = target_project_id or HEARTBEAT_PROJECT
    if not await check_project_permission(permission_project):
        raise HTTPException(status_code=403, detail=f"Heartbeat project permission is off for {permission_project}")

    # Dispatch via Hatchet (fire-and-forget)
    heartbeat_session_id = create_heartbeat_session_id()
    await record_heartbeat_attempt(session_id=heartbeat_session_id)
    claim_token = await set_heartbeat_running(
        session_id=heartbeat_session_id,
        trigger="manual_api",
        project_id=permission_project,
        only_if_missing=True,
    )
    if not claim_token:
        running_info = await _get_effective_running_info()
        return JSONResponse(
            status_code=409,
            content={
                "error": "http_error",
                "message": (
                    f"Heartbeat already in progress (started {running_info['elapsed_seconds']}s ago)"
                    if running_info
                    else "Heartbeat already in progress"
                ),
                "running_session_id": running_info.get("session_id") if running_info else None,
            },
        )
    try:
        await persona_heartbeat_task.aio_run_no_wait(
            input=HeartbeatInput(
                manual=True,
                target_project_id=target_project_id,
                heartbeat_session_id=heartbeat_session_id,
                running_claimed=True,
                running_claim_token=claim_token,
            )
        )
    except Exception as exc:
        await clear_heartbeat_running(
            claim_token=claim_token,
            session_id=heartbeat_session_id,
        )
        logger.exception("Failed to dispatch manual heartbeat for target=%s", target_project_id or "persona-sandbox")
        raise HTTPException(status_code=503, detail=f"Failed to dispatch heartbeat: {exc}") from exc
    logger.info("Manual heartbeat triggered via API for target=%s", target_project_id or "persona-sandbox")

    if target_project_id:
        return HeartbeatTriggerResponse(
            status="dispatched",
            message=f"Heartbeat triggered for {target_project_id}",
            session_id=heartbeat_session_id,
        )
    return HeartbeatTriggerResponse(
        status="dispatched",
        message="Heartbeat triggered",
        session_id=heartbeat_session_id,
    )
