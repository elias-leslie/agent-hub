"""Admin API endpoints for kill switch and usage control."""

import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import ClientControl

from .admin_handlers import (
    client_to_response,
    process_audit_requests,
    process_blocked_requests,
    process_unknown_callers,
)
from .admin_redis import (
    MAX_AUDIT_LOG_SIZE,
    MAX_BLOCKED_LOG_SIZE,
    REDIS_KEY_AUDIT_LOG,
    REDIS_KEY_BLOCKED_REQUESTS,
    REDIS_KEY_UNKNOWN_CALLERS,
    get_admin_redis,
)
from .admin_schemas import (
    BlockedRequestsResponse,
    ClientControlResponse,
    ClientListResponse,
    DisableRequest,
    RequestAuditResponse,
    UnknownCallersResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# Client endpoints
@router.get("/clients", response_model=ClientListResponse)
async def list_clients(
    db: Annotated[AsyncSession, Depends(get_db)],
    include_enabled: bool = True,
    include_disabled: bool = True,
) -> ClientListResponse:
    """List all registered clients with their kill switch status."""
    query = select(ClientControl)

    if not include_enabled:
        query = query.where(ClientControl.enabled == False)  # noqa: E712
    if not include_disabled:
        query = query.where(ClientControl.enabled == True)  # noqa: E712

    query = query.order_by(ClientControl.client_name)
    result = await db.execute(query)
    clients = result.scalars().all()

    return ClientListResponse(
        clients=[client_to_response(c) for c in clients],
        total=len(clients),
    )


@router.get("/clients/{client_name}", response_model=ClientControlResponse)
async def get_client(
    client_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClientControlResponse:
    """Get a specific client's status."""
    result = await db.execute(select(ClientControl).where(ClientControl.client_name == client_name))
    client = result.scalar_one_or_none()

    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client_to_response(client)


@router.post("/clients/{client_name}/disable", response_model=ClientControlResponse)
async def disable_client(
    client_name: str,
    request: DisableRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClientControlResponse:
    """Disable a client. Blocked requests will get 403 with retry_after=-1."""
    result = await db.execute(select(ClientControl).where(ClientControl.client_name == client_name))
    client = result.scalar_one_or_none()

    if not client:
        # Create new client control record
        client = ClientControl(
            client_name=client_name,
            enabled=False,
            disabled_at=datetime.now(UTC),
            disabled_by=request.disabled_by,
            reason=request.reason,
        )
        db.add(client)
    else:
        if not client.enabled:
            raise HTTPException(status_code=400, detail="Client already disabled")
        client.enabled = False
        client.disabled_at = datetime.now(UTC)
        client.disabled_by = request.disabled_by
        client.reason = request.reason

    await db.commit()
    await db.refresh(client)
    return client_to_response(client)


@router.delete("/clients/{client_name}/disable", response_model=ClientControlResponse)
async def enable_client(
    client_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClientControlResponse:
    """Re-enable a disabled client."""
    result = await db.execute(select(ClientControl).where(ClientControl.client_name == client_name))
    client = result.scalar_one_or_none()

    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    if client.enabled:
        raise HTTPException(status_code=400, detail="Client already enabled")

    client.enabled = True
    client.disabled_at = None
    client.disabled_by = None
    client.reason = None

    await db.commit()
    await db.refresh(client)
    return client_to_response(client)


# Blocked requests log endpoint
@router.get("/blocked-requests", response_model=BlockedRequestsResponse)
async def get_blocked_requests(
    limit: int = Query(default=100, ge=1, le=1000, description="Max entries to return"),
    client_name: str | None = Query(default=None, description="Filter by client"),
) -> BlockedRequestsResponse:
    """Get recent blocked request log entries."""
    redis = await get_admin_redis()
    if redis is None:
        return BlockedRequestsResponse(requests=[], total=0)

    try:
        raw_entries = await redis.lrange(REDIS_KEY_BLOCKED_REQUESTS, 0, MAX_BLOCKED_LOG_SIZE - 1)
        requests = process_blocked_requests(raw_entries, client_name, limit)
        return BlockedRequestsResponse(requests=requests, total=len(requests))
    except Exception as e:
        logger.warning(f"Failed to read blocked requests from Redis: {e}")
        return BlockedRequestsResponse(requests=[], total=0)


# Request audit log endpoint (ALL requests, not just blocked)
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
    except Exception as e:
        logger.warning(f"Failed to clear unknown callers from Redis: {e}")
        return {"cleared": 0, "message": f"Error: {e}"}


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
    except Exception as e:
        logger.warning(f"Failed to clear audit log from Redis: {e}")
        return {"cleared": 0, "message": f"Error: {e}"}
