"""Admin API endpoints for schedules, request audit and session diagnostics."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
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
