"""Admin API endpoints for kill switch and usage control."""

from collections import defaultdict
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import ClientControl, ClientPurposeControl, PurposeControl

router = APIRouter(prefix="/admin", tags=["admin"])


# Request/Response schemas
class ClientControlResponse(BaseModel):
    """Response for client control status."""

    client_name: str
    enabled: bool
    disabled_at: datetime | None
    disabled_by: str | None
    reason: str | None
    created_at: datetime
    updated_at: datetime


class PurposeControlResponse(BaseModel):
    """Response for purpose control status."""

    purpose: str
    enabled: bool
    disabled_at: datetime | None
    disabled_by: str | None
    reason: str | None
    created_at: datetime
    updated_at: datetime


class ClientPurposeControlResponse(BaseModel):
    """Response for client+purpose combo control status."""

    client_name: str
    purpose: str
    enabled: bool
    disabled_at: datetime | None
    disabled_by: str | None
    reason: str | None
    created_at: datetime
    updated_at: datetime


class DisableRequest(BaseModel):
    """Request to disable a client or purpose."""

    reason: str | None = Field(default=None, max_length=500, description="Reason for disabling")
    disabled_by: str | None = Field(
        default=None, max_length=100, description="User/admin who disabled"
    )


class ClientListResponse(BaseModel):
    """Response for listing clients."""

    clients: list[ClientControlResponse]
    total: int


class PurposeListResponse(BaseModel):
    """Response for listing purposes."""

    purposes: list[PurposeControlResponse]
    total: int


class ClientPurposeListResponse(BaseModel):
    """Response for listing client+purpose combos."""

    combos: list[ClientPurposeControlResponse]
    total: int


class BlockedRequestLog(BaseModel):
    """A log entry for a blocked request."""

    timestamp: datetime
    client_name: str | None
    purpose: str | None
    source_path: str | None
    block_reason: str
    endpoint: str


class BlockedRequestsResponse(BaseModel):
    """Response for blocked requests log."""

    requests: list[BlockedRequestLog]
    total: int


class RequestAuditLog(BaseModel):
    """A log entry for any API request (for visibility)."""

    timestamp: datetime
    endpoint: str
    method: str
    client_name: str | None
    source_path: str | None
    user_agent: str | None
    referer: str | None
    client_ip: str | None
    status: str  # "allowed", "blocked", "unknown_client"


class RequestAuditResponse(BaseModel):
    """Response for request audit log."""

    requests: list[RequestAuditLog]
    total: int


class UnknownCallerStats(BaseModel):
    """Stats for an unknown caller (no X-Source-Client)."""

    fingerprint: str
    count: int
    first_seen: datetime | None
    last_seen: datetime | None
    endpoints: list[str]
    user_agents: list[str]


class UnknownCallersResponse(BaseModel):
    """Response for unknown callers list."""

    callers: list[UnknownCallerStats]
    total: int
    total_requests: int


# In-memory store for blocked requests (could be Redis in production)
_blocked_requests_log: list[dict] = []
MAX_BLOCKED_LOG_SIZE = 1000

# In-memory store for ALL request audit (not just blocked)
_request_audit_log: list[dict] = []
MAX_AUDIT_LOG_SIZE = 2000

# Aggregated stats for unknown callers (no X-Source-Client header)
_unknown_caller_stats: dict[str, dict] = defaultdict(
    lambda: {
        "count": 0,
        "first_seen": None,
        "last_seen": None,
        "endpoints": set(),
        "user_agents": set(),
    }
)


def log_blocked_request(
    client_name: str | None,
    purpose: str | None,
    source_path: str | None,
    block_reason: str,
    endpoint: str,
) -> None:
    """Log a blocked request for admin visibility."""
    global _blocked_requests_log
    _blocked_requests_log.append(
        {
            "timestamp": datetime.now(UTC),
            "client_name": client_name,
            "purpose": purpose,
            "source_path": source_path,
            "block_reason": block_reason,
            "endpoint": endpoint,
        }
    )
    # Keep only recent entries
    if len(_blocked_requests_log) > MAX_BLOCKED_LOG_SIZE:
        _blocked_requests_log = _blocked_requests_log[-MAX_BLOCKED_LOG_SIZE:]


def log_request_audit(
    endpoint: str,
    method: str,
    client_name: str | None,
    source_path: str | None,
    user_agent: str | None,
    referer: str | None,
    client_ip: str | None,
    status: str,  # "allowed", "blocked", "unknown_client"
) -> None:
    """Log all requests to sensitive endpoints for audit visibility.

    This provides visibility into WHO is calling Agent Hub, even if they
    don't provide proper X-Source-Client headers.
    """
    global _request_audit_log, _unknown_caller_stats
    now = datetime.now(UTC)

    entry = {
        "timestamp": now,
        "endpoint": endpoint,
        "method": method,
        "client_name": client_name,
        "source_path": source_path,
        "user_agent": user_agent,
        "referer": referer,
        "client_ip": client_ip,
        "status": status,
    }

    _request_audit_log.append(entry)

    # Keep only recent entries
    if len(_request_audit_log) > MAX_AUDIT_LOG_SIZE:
        _request_audit_log = _request_audit_log[-MAX_AUDIT_LOG_SIZE:]

    # Track unknown callers (no X-Source-Client)
    if not client_name or client_name == "<unknown>":
        # Create a fingerprint from available info
        fingerprint = f"{user_agent or 'no-ua'}|{referer or 'no-ref'}|{client_ip or 'no-ip'}"
        stats = _unknown_caller_stats[fingerprint]
        stats["count"] += 1
        if stats["first_seen"] is None:
            stats["first_seen"] = now
        stats["last_seen"] = now
        stats["endpoints"].add(endpoint)
        if user_agent:
            stats["user_agents"].add(user_agent)


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
        clients=[
            ClientControlResponse(
                client_name=c.client_name,
                enabled=c.enabled,
                disabled_at=c.disabled_at,
                disabled_by=c.disabled_by,
                reason=c.reason,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
            for c in clients
        ],
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

    return ClientControlResponse(
        client_name=client.client_name,
        enabled=client.enabled,
        disabled_at=client.disabled_at,
        disabled_by=client.disabled_by,
        reason=client.reason,
        created_at=client.created_at,
        updated_at=client.updated_at,
    )


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

    return ClientControlResponse(
        client_name=client.client_name,
        enabled=client.enabled,
        disabled_at=client.disabled_at,
        disabled_by=client.disabled_by,
        reason=client.reason,
        created_at=client.created_at,
        updated_at=client.updated_at,
    )


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

    return ClientControlResponse(
        client_name=client.client_name,
        enabled=client.enabled,
        disabled_at=client.disabled_at,
        disabled_by=client.disabled_by,
        reason=client.reason,
        created_at=client.created_at,
        updated_at=client.updated_at,
    )


# Purpose endpoints
@router.get("/purposes", response_model=PurposeListResponse)
async def list_purposes(
    db: Annotated[AsyncSession, Depends(get_db)],
    include_enabled: bool = True,
    include_disabled: bool = True,
) -> PurposeListResponse:
    """List all registered purposes with their kill switch status."""
    query = select(PurposeControl)

    if not include_enabled:
        query = query.where(PurposeControl.enabled == False)  # noqa: E712
    if not include_disabled:
        query = query.where(PurposeControl.enabled == True)  # noqa: E712

    query = query.order_by(PurposeControl.purpose)
    result = await db.execute(query)
    purposes = result.scalars().all()

    return PurposeListResponse(
        purposes=[
            PurposeControlResponse(
                purpose=p.purpose,
                enabled=p.enabled,
                disabled_at=p.disabled_at,
                disabled_by=p.disabled_by,
                reason=p.reason,
                created_at=p.created_at,
                updated_at=p.updated_at,
            )
            for p in purposes
        ],
        total=len(purposes),
    )


@router.get("/purposes/{purpose}", response_model=PurposeControlResponse)
async def get_purpose(
    purpose: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PurposeControlResponse:
    """Get a specific purpose's status."""
    result = await db.execute(select(PurposeControl).where(PurposeControl.purpose == purpose))
    purpose_control = result.scalar_one_or_none()

    if not purpose_control:
        raise HTTPException(status_code=404, detail="Purpose not found")

    return PurposeControlResponse(
        purpose=purpose_control.purpose,
        enabled=purpose_control.enabled,
        disabled_at=purpose_control.disabled_at,
        disabled_by=purpose_control.disabled_by,
        reason=purpose_control.reason,
        created_at=purpose_control.created_at,
        updated_at=purpose_control.updated_at,
    )


@router.post("/purposes/{purpose}/disable", response_model=PurposeControlResponse)
async def disable_purpose(
    purpose: str,
    request: DisableRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PurposeControlResponse:
    """Disable a purpose. Blocked requests will get 403 with retry_after=-1."""
    result = await db.execute(select(PurposeControl).where(PurposeControl.purpose == purpose))
    purpose_control = result.scalar_one_or_none()

    if not purpose_control:
        # Create new purpose control record
        purpose_control = PurposeControl(
            purpose=purpose,
            enabled=False,
            disabled_at=datetime.now(UTC),
            disabled_by=request.disabled_by,
            reason=request.reason,
        )
        db.add(purpose_control)
    else:
        if not purpose_control.enabled:
            raise HTTPException(status_code=400, detail="Purpose already disabled")
        purpose_control.enabled = False
        purpose_control.disabled_at = datetime.now(UTC)
        purpose_control.disabled_by = request.disabled_by
        purpose_control.reason = request.reason

    await db.commit()
    await db.refresh(purpose_control)

    return PurposeControlResponse(
        purpose=purpose_control.purpose,
        enabled=purpose_control.enabled,
        disabled_at=purpose_control.disabled_at,
        disabled_by=purpose_control.disabled_by,
        reason=purpose_control.reason,
        created_at=purpose_control.created_at,
        updated_at=purpose_control.updated_at,
    )


@router.delete("/purposes/{purpose}/disable", response_model=PurposeControlResponse)
async def enable_purpose(
    purpose: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PurposeControlResponse:
    """Re-enable a disabled purpose."""
    result = await db.execute(select(PurposeControl).where(PurposeControl.purpose == purpose))
    purpose_control = result.scalar_one_or_none()

    if not purpose_control:
        raise HTTPException(status_code=404, detail="Purpose not found")

    if purpose_control.enabled:
        raise HTTPException(status_code=400, detail="Purpose already enabled")

    purpose_control.enabled = True
    purpose_control.disabled_at = None
    purpose_control.disabled_by = None
    purpose_control.reason = None

    await db.commit()
    await db.refresh(purpose_control)

    return PurposeControlResponse(
        purpose=purpose_control.purpose,
        enabled=purpose_control.enabled,
        disabled_at=purpose_control.disabled_at,
        disabled_by=purpose_control.disabled_by,
        reason=purpose_control.reason,
        created_at=purpose_control.created_at,
        updated_at=purpose_control.updated_at,
    )


# Client+Purpose combo endpoints
@router.get("/combos", response_model=ClientPurposeListResponse)
async def list_client_purpose_combos(
    db: Annotated[AsyncSession, Depends(get_db)],
    client_name: str | None = Query(default=None, description="Filter by client"),
    purpose: str | None = Query(default=None, description="Filter by purpose"),
) -> ClientPurposeListResponse:
    """List all client+purpose combo controls."""
    query = select(ClientPurposeControl)

    if client_name:
        query = query.where(ClientPurposeControl.client_name == client_name)
    if purpose:
        query = query.where(ClientPurposeControl.purpose == purpose)

    query = query.order_by(ClientPurposeControl.client_name, ClientPurposeControl.purpose)
    result = await db.execute(query)
    combos = result.scalars().all()

    return ClientPurposeListResponse(
        combos=[
            ClientPurposeControlResponse(
                client_name=c.client_name,
                purpose=c.purpose,
                enabled=c.enabled,
                disabled_at=c.disabled_at,
                disabled_by=c.disabled_by,
                reason=c.reason,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
            for c in combos
        ],
        total=len(combos),
    )


@router.post("/combos/{client_name}/{purpose}/disable", response_model=ClientPurposeControlResponse)
async def disable_client_purpose_combo(
    client_name: str,
    purpose: str,
    request: DisableRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClientPurposeControlResponse:
    """Disable a specific client+purpose combination."""
    result = await db.execute(
        select(ClientPurposeControl).where(
            ClientPurposeControl.client_name == client_name,
            ClientPurposeControl.purpose == purpose,
        )
    )
    combo = result.scalar_one_or_none()

    if not combo:
        # Create new combo control record
        combo = ClientPurposeControl(
            client_name=client_name,
            purpose=purpose,
            enabled=False,
            disabled_at=datetime.now(UTC),
            disabled_by=request.disabled_by,
            reason=request.reason,
        )
        db.add(combo)
    else:
        if not combo.enabled:
            raise HTTPException(status_code=400, detail="Combination already disabled")
        combo.enabled = False
        combo.disabled_at = datetime.now(UTC)
        combo.disabled_by = request.disabled_by
        combo.reason = request.reason

    await db.commit()
    await db.refresh(combo)

    return ClientPurposeControlResponse(
        client_name=combo.client_name,
        purpose=combo.purpose,
        enabled=combo.enabled,
        disabled_at=combo.disabled_at,
        disabled_by=combo.disabled_by,
        reason=combo.reason,
        created_at=combo.created_at,
        updated_at=combo.updated_at,
    )


@router.delete(
    "/combos/{client_name}/{purpose}/disable", response_model=ClientPurposeControlResponse
)
async def enable_client_purpose_combo(
    client_name: str,
    purpose: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClientPurposeControlResponse:
    """Re-enable a disabled client+purpose combination."""
    result = await db.execute(
        select(ClientPurposeControl).where(
            ClientPurposeControl.client_name == client_name,
            ClientPurposeControl.purpose == purpose,
        )
    )
    combo = result.scalar_one_or_none()

    if not combo:
        raise HTTPException(status_code=404, detail="Combination not found")

    if combo.enabled:
        raise HTTPException(status_code=400, detail="Combination already enabled")

    combo.enabled = True
    combo.disabled_at = None
    combo.disabled_by = None
    combo.reason = None

    await db.commit()
    await db.refresh(combo)

    return ClientPurposeControlResponse(
        client_name=combo.client_name,
        purpose=combo.purpose,
        enabled=combo.enabled,
        disabled_at=combo.disabled_at,
        disabled_by=combo.disabled_by,
        reason=combo.reason,
        created_at=combo.created_at,
        updated_at=combo.updated_at,
    )


# Blocked requests log endpoint
@router.get("/blocked-requests", response_model=BlockedRequestsResponse)
async def get_blocked_requests(
    limit: int = Query(default=100, ge=1, le=1000, description="Max entries to return"),
    client_name: str | None = Query(default=None, description="Filter by client"),
) -> BlockedRequestsResponse:
    """Get recent blocked request log entries."""
    requests = _blocked_requests_log.copy()

    # Filter by client if specified
    if client_name:
        requests = [r for r in requests if r.get("client_name") == client_name]

    # Sort by timestamp descending (most recent first)
    requests.sort(key=lambda x: x["timestamp"], reverse=True)

    # Apply limit
    requests = requests[:limit]

    return BlockedRequestsResponse(
        requests=[
            BlockedRequestLog(
                timestamp=r["timestamp"],
                client_name=r.get("client_name"),
                purpose=r.get("purpose"),
                source_path=r.get("source_path"),
                block_reason=r["block_reason"],
                endpoint=r["endpoint"],
            )
            for r in requests
        ],
        total=len(requests),
    )


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
    requests = _request_audit_log.copy()

    # Filter by status if specified
    if status:
        requests = [r for r in requests if r.get("status") == status]

    # Filter by endpoint pattern if specified
    if endpoint_filter:
        requests = [r for r in requests if endpoint_filter in r.get("endpoint", "")]

    # Sort by timestamp descending (most recent first)
    requests.sort(key=lambda x: x["timestamp"], reverse=True)

    # Apply limit
    requests = requests[:limit]

    return RequestAuditResponse(
        requests=[
            RequestAuditLog(
                timestamp=r["timestamp"],
                endpoint=r["endpoint"],
                method=r["method"],
                client_name=r.get("client_name"),
                source_path=r.get("source_path"),
                user_agent=r.get("user_agent"),
                referer=r.get("referer"),
                client_ip=r.get("client_ip"),
                status=r["status"],
            )
            for r in requests
        ],
        total=len(requests),
    )


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
    callers = []
    total_requests = 0

    for fingerprint, stats in _unknown_caller_stats.items():
        if stats["count"] >= min_count:
            callers.append(
                UnknownCallerStats(
                    fingerprint=fingerprint,
                    count=stats["count"],
                    first_seen=stats["first_seen"],
                    last_seen=stats["last_seen"],
                    endpoints=list(stats["endpoints"]),
                    user_agents=list(stats["user_agents"]),
                )
            )
            total_requests += stats["count"]

    # Sort by count descending (most active first)
    callers.sort(key=lambda x: x.count, reverse=True)

    return UnknownCallersResponse(
        callers=callers,
        total=len(callers),
        total_requests=total_requests,
    )


@router.delete("/unknown-callers")
async def clear_unknown_callers() -> dict:
    """Clear the unknown callers tracking data.

    Use after you've reviewed and addressed the unknown callers.
    """
    global _unknown_caller_stats
    count = len(_unknown_caller_stats)
    _unknown_caller_stats.clear()
    return {"cleared": count, "message": f"Cleared {count} unknown caller entries"}


@router.delete("/request-audit")
async def clear_request_audit() -> dict:
    """Clear the request audit log.

    Use after you've reviewed the audit log.
    """
    global _request_audit_log
    count = len(_request_audit_log)
    _request_audit_log.clear()
    return {"cleared": count, "message": f"Cleared {count} audit log entries"}
