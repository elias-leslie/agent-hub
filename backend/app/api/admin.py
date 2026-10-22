"""Admin API endpoints for schedules, request audit and session diagnostics."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.automation_guidance import automation_moved
from app.db import get_db

from .admin_handlers import (
    process_audit_requests,
    process_unknown_callers,
)
from .admin_redis import (
    MAX_AUDIT_LOG_SIZE,
    REDIS_KEY_AUDIT_LOG,
    REDIS_KEY_UNKNOWN_CALLERS,
    get_admin_redis,
)
from .admin_schemas import (
    RequestAuditResponse,
    SessionHotspotsResponse,
    UnknownCallersResponse,
    WorkflowScheduleResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/schedules", response_model=list[WorkflowScheduleResponse])
async def list_workflow_schedules(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[WorkflowScheduleResponse]:
    """List every static Hatchet cron workflow with its enablement state."""
    from app.services.workflow_schedule_registry import list_workflow_schedule_states

    states = await list_workflow_schedule_states(db)
    return [WorkflowScheduleResponse(**state) for state in states]


@router.patch("/schedules/{schedule_id}")
async def update_workflow_schedule(schedule_id: str) -> None:
    """Retired writer; central Automations owns static Hatchet schedules."""
    raise automation_moved()


# Request audit log endpoint
@router.get("/request-audit", response_model=RequestAuditResponse)
async def get_request_audit(
    limit: int = Query(default=100, ge=1, le=1000, description="Max entries to return"),
    status: str | None = Query(
        default=None, description="Filter by status: allowed, blocked, unknown_client"
    ),
    endpoint_filter: str | None = Query(
        default=None, alias="endpoint", description="Filter by endpoint pattern"
    ),
) -> RequestAuditResponse:
    """Get recent request audit log for visibility into ALL API traffic.

    Use this to see what's connecting to Agent Hub, even before blocking.
    """
    redis = await get_admin_redis()
    if redis is None:
        return RequestAuditResponse(requests=[], total=0)

    try:
        raw_entries = await redis.lrange(REDIS_KEY_AUDIT_LOG, 0, MAX_AUDIT_LOG_SIZE - 1)
        requests = process_audit_requests(raw_entries, status, endpoint_filter, limit)
        return RequestAuditResponse(requests=requests, total=len(requests))
    except Exception as e:
        logger.warning(f"Failed to read audit log from Redis: {e}")
        return RequestAuditResponse(requests=[], total=0)


@router.get("/session-hotspots", response_model=SessionHotspotsResponse)
async def get_session_hotspots(
    db: Annotated[AsyncSession, Depends(get_db)],
    hours: int = Query(default=24, ge=1, le=168, description="Window size in hours"),
    limit: int = Query(default=5, ge=1, le=20, description="Rows per hotspot section"),
) -> SessionHotspotsResponse:
    """Return the current churn / token-waste hotspot summary."""
    from app.services.admin_session_hotspots import build_session_hotspot_snapshot

    payload = await build_session_hotspot_snapshot(db, hours=hours, limit=limit)
    return SessionHotspotsResponse(**payload)


@router.get("/session-efficiency")
async def get_session_efficiency(
    db: Annotated[AsyncSession, Depends(get_db)],
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=5, ge=1, le=20),
    until: datetime | None = Query(default=None, description="Exclusive UTC window end; pin for repeatable comparisons"),
    project_id: str | None = Query(default=None, max_length=100),
    provider: str | None = Query(default=None, max_length=20),
    model: str | None = Query(default=None, max_length=100, description="Requested session model, matching Sessions; not proof of served model"),
    session_id: str | None = Query(default=None, max_length=36),
    accounting_start: datetime | None = Query(default=None),
    accounting_end: datetime | None = Query(default=None),
    work_role: str | None = Query(default=None),
    harness: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    agent_slug: str | None = Query(default=None),
    parent_session_id: str | None = Query(default=None),
    session_type: str | None = Query(default=None),
    external_id: str | None = Query(default=None),
    roots_only: bool = Query(default=False),
    exclude_benchmarks: bool = Query(default=False),
) -> dict[str, Any]:
    """Read existing session observations, filtered before the event cap. No task binding required."""
    from app.api.sessions import _list_filters
    from app.services.admin_activity_cost import build_activity_cost_snapshot
    from app.services.session_accounting import accounting_window

    current = datetime.now(UTC)
    end = until or current
    if end.tzinfo is None or end > current:
        raise HTTPException(status_code=422, detail="until must include a timezone and cannot be in the future")
    end = end.astimezone(UTC)
    try:
        start, end, _ = accounting_window(accounting_start, accounting_end, None) if accounting_start is not None or accounting_end is not None else (end - timedelta(hours=hours), end, None)
        filters = _list_filters(project_id=project_id, status=status, agent_slug=agent_slug, parent_session_id=parent_session_id,
            session_type=session_type, external_id=external_id, q=q, kind=kind, since=since,
            exclude_benchmarks=exclude_benchmarks, model=model, roots_only=roots_only, work_role=work_role, harness=harness)
        payload = await build_activity_cost_snapshot(
            db, cutoff=start, now=end, limit=limit, provider=provider, session_id=session_id,
            list_filters=filters,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload["filters"] = {"project_id": project_id, "provider": provider, "model": model, "session_id": session_id,
                          "work_role": work_role, "harness": harness, "kind": kind, "status": status, "q": q,
                          "since": since.isoformat() if since else None, "roots_only": roots_only, "exclude_benchmarks": exclude_benchmarks,
                          "agent_slug": agent_slug, "parent_session_id": parent_session_id, "session_type": session_type, "external_id": external_id}
    return payload


# Unknown callers endpoint
@router.get("/unknown-callers", response_model=UnknownCallersResponse)
async def get_unknown_callers(
    min_count: int = Query(default=1, ge=1, description="Minimum request count to include"),
) -> UnknownCallersResponse:
    """Get aggregated stats on callers that didn't provide X-Source-Client.

    This helps identify services/scripts that should be updated to include headers,
    or that should be blocked entirely.

    Callers are fingerprinted by: User-Agent + Referer + IP
    """
    redis = await get_admin_redis()
    if redis is None:
        return UnknownCallersResponse(callers=[], total=0, total_requests=0)

    try:
        raw_stats = await redis.hgetall(REDIS_KEY_UNKNOWN_CALLERS)
        callers, total_requests = process_unknown_callers(raw_stats, min_count)
        return UnknownCallersResponse(callers=callers, total=len(callers), total_requests=total_requests)
    except Exception as e:
        logger.warning(f"Failed to read unknown callers from Redis: {e}")
        return UnknownCallersResponse(callers=[], total=0, total_requests=0)


@router.delete("/unknown-callers")
async def clear_unknown_callers() -> dict[str, Any]:
    """Clear the unknown callers tracking data.

    Use after you've reviewed and addressed the unknown callers.
    """
    redis = await get_admin_redis()
    if redis is None:
        return {"cleared": 0, "message": "Redis unavailable"}

    try:
        # Get count before deleting
        count = await redis.hlen(REDIS_KEY_UNKNOWN_CALLERS)
        await redis.delete(REDIS_KEY_UNKNOWN_CALLERS)
        return {"cleared": count, "message": f"Cleared {count} unknown caller entries"}
    except Exception:
        logger.warning("Failed to clear unknown callers from Redis", exc_info=True)
        return {"cleared": 0, "message": "Failed to clear unknown callers"}


@router.delete("/request-audit")
async def clear_request_audit() -> dict[str, Any]:
    """Clear the request audit log.

    Use after you've reviewed the audit log.
    """
    redis = await get_admin_redis()
    if redis is None:
        return {"cleared": 0, "message": "Redis unavailable"}

    try:
        # Get count before deleting
        count = await redis.llen(REDIS_KEY_AUDIT_LOG)
        await redis.delete(REDIS_KEY_AUDIT_LOG)
        return {"cleared": count, "message": f"Cleared {count} audit log entries"}
    except Exception:
        logger.warning("Failed to clear audit log from Redis", exc_info=True)
        return {"cleared": 0, "message": "Failed to clear audit log"}
