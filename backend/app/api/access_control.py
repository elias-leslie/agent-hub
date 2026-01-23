"""Access Control API endpoints for client management and request logging.

Replaces the old kill switch admin endpoints with cryptographic client auth.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Client, RequestLog
from app.services.client_auth import ClientAuthService

router = APIRouter(prefix="/access-control", tags=["access-control"])


# Request/Response schemas
class ClientCreateRequest(BaseModel):
    """Request to create a new client."""

    display_name: str = Field(..., min_length=1, max_length=100)
    client_type: str = Field(default="external", pattern="^(internal|external|service)$")
    rate_limit_rpm: int = Field(default=60, ge=1, le=10000)
    rate_limit_tpm: int = Field(default=100000, ge=1000, le=10000000)


class ClientCreateResponse(BaseModel):
    """Response for client creation with the one-time secret."""

    client_id: str
    display_name: str
    secret: str  # Show only once!
    secret_prefix: str
    client_type: str
    status: str
    rate_limit_rpm: int
    rate_limit_tpm: int
    created_at: datetime
    message: str = "Store this secret securely - it will not be shown again!"


class ClientResponse(BaseModel):
    """Response for client details (without secret)."""

    client_id: str
    display_name: str
    secret_prefix: str
    client_type: str
    status: str
    rate_limit_rpm: int
    rate_limit_tpm: int
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None
    suspended_at: datetime | None
    suspended_by: str | None
    suspension_reason: str | None


class ClientListResponse(BaseModel):
    """Response for listing clients."""

    clients: list[ClientResponse]
    total: int


class ClientStatsResponse(BaseModel):
    """Response for client statistics."""

    total_clients: int
    active_clients: int
    suspended_clients: int
    blocked_clients: int
    blocked_requests_today: int
    total_requests_today: int


class SuspendRequest(BaseModel):
    """Request to suspend a client."""

    reason: str = Field(..., min_length=1, max_length=500)
    suspended_by: str = Field(default="admin", max_length=100)


class BlockRequest(BaseModel):
    """Request to permanently block a client."""

    reason: str = Field(..., min_length=1, max_length=500)
    blocked_by: str = Field(default="admin", max_length=100)


class SecretRotateResponse(BaseModel):
    """Response for secret rotation."""

    client_id: str
    secret: str  # New secret - show only once!
    secret_prefix: str
    message: str = "Store this new secret securely - it will not be shown again!"


class RequestLogEntry(BaseModel):
    """A request log entry."""

    id: int
    client_id: str | None
    client_display_name: str | None
    request_source: str | None
    endpoint: str
    method: str
    status_code: int
    rejection_reason: str | None
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: int | None
    model: str | None
    created_at: datetime


class RequestLogResponse(BaseModel):
    """Response for request log listing."""

    requests: list[RequestLogEntry]
    total: int


# Stats endpoint
@router.get("/stats", response_model=ClientStatsResponse)
async def get_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClientStatsResponse:
    """Get access control statistics for dashboard."""
    # Count clients by status
    total_result = await db.execute(select(func.count()).select_from(Client))
    total_clients = total_result.scalar() or 0

    active_result = await db.execute(
        select(func.count()).select_from(Client).where(Client.status == "active")
    )
    active_clients = active_result.scalar() or 0

    suspended_result = await db.execute(
        select(func.count()).select_from(Client).where(Client.status == "suspended")
    )
    suspended_clients = suspended_result.scalar() or 0

    blocked_result = await db.execute(
        select(func.count()).select_from(Client).where(Client.status == "blocked")
    )
    blocked_clients = blocked_result.scalar() or 0

    # Count requests today
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    total_requests_result = await db.execute(
        select(func.count()).select_from(RequestLog).where(RequestLog.created_at >= today_start)
    )
    total_requests_today = total_requests_result.scalar() or 0

    blocked_requests_result = await db.execute(
        select(func.count())
        .select_from(RequestLog)
        .where(
            RequestLog.created_at >= today_start,
            RequestLog.rejection_reason.isnot(None),
        )
    )
    blocked_requests_today = blocked_requests_result.scalar() or 0

    return ClientStatsResponse(
        total_clients=total_clients,
        active_clients=active_clients,
        suspended_clients=suspended_clients,
        blocked_clients=blocked_clients,
        blocked_requests_today=blocked_requests_today,
        total_requests_today=total_requests_today,
    )


# Client CRUD endpoints
@router.post("/clients", response_model=ClientCreateResponse, status_code=201)
async def create_client(
    request: ClientCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClientCreateResponse:
    """Register a new client and return the one-time secret."""
    service = ClientAuthService(db)
    registration = await service.register_client(
        display_name=request.display_name,
        client_type=request.client_type,
        rate_limit_rpm=request.rate_limit_rpm,
        rate_limit_tpm=request.rate_limit_tpm,
    )

    # Get full client for response
    client = await service.get_client(registration.client_id)

    return ClientCreateResponse(
        client_id=registration.client_id,
        display_name=registration.display_name,
        secret=registration.secret,
        secret_prefix=registration.secret_prefix,
        client_type=client.client_type if client else request.client_type,
        status="active",
        rate_limit_rpm=request.rate_limit_rpm,
        rate_limit_tpm=request.rate_limit_tpm,
        created_at=client.created_at if client else datetime.now(UTC),
    )


@router.get("/clients", response_model=ClientListResponse)
async def list_clients(
    db: Annotated[AsyncSession, Depends(get_db)],
    status: str | None = Query(default=None, description="Filter by status"),
    client_type: str | None = Query(default=None, description="Filter by client type"),
) -> ClientListResponse:
    """List all registered clients."""
    query = select(Client)

    if status:
        query = query.where(Client.status == status)
    if client_type:
        query = query.where(Client.client_type == client_type)

    query = query.order_by(Client.display_name)
    result = await db.execute(query)
    clients = result.scalars().all()

    return ClientListResponse(
        clients=[
            ClientResponse(
                client_id=c.id,
                display_name=c.display_name,
                secret_prefix=c.secret_prefix,
                client_type=c.client_type,
                status=c.status,
                rate_limit_rpm=c.rate_limit_rpm,
                rate_limit_tpm=c.rate_limit_tpm,
                created_at=c.created_at,
                updated_at=c.updated_at,
                last_used_at=c.last_used_at,
                suspended_at=c.suspended_at,
                suspended_by=c.suspended_by,
                suspension_reason=c.suspension_reason,
            )
            for c in clients
        ],
        total=len(clients),
    )


@router.get("/clients/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClientResponse:
    """Get a specific client's details."""
    service = ClientAuthService(db)
    client = await service.get_client(client_id)

    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    return ClientResponse(
        client_id=client.id,
        display_name=client.display_name,
        secret_prefix=client.secret_prefix,
        client_type=client.client_type,
        status=client.status,
        rate_limit_rpm=client.rate_limit_rpm,
        rate_limit_tpm=client.rate_limit_tpm,
        created_at=client.created_at,
        updated_at=client.updated_at,
        last_used_at=client.last_used_at,
        suspended_at=client.suspended_at,
        suspended_by=client.suspended_by,
        suspension_reason=client.suspension_reason,
    )


@router.post("/clients/{client_id}/suspend", response_model=ClientResponse)
async def suspend_client(
    client_id: str,
    request: SuspendRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClientResponse:
    """Suspend a client (temporary block)."""
    service = ClientAuthService(db)
    success = await service.suspend_client(
        client_id=client_id,
        reason=request.reason,
        suspended_by=request.suspended_by,
    )

    if not success:
        raise HTTPException(status_code=404, detail="Client not found")

    client = await service.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    return ClientResponse(
        client_id=client.id,
        display_name=client.display_name,
        secret_prefix=client.secret_prefix,
        client_type=client.client_type,
        status=client.status,
        rate_limit_rpm=client.rate_limit_rpm,
        rate_limit_tpm=client.rate_limit_tpm,
        created_at=client.created_at,
        updated_at=client.updated_at,
        last_used_at=client.last_used_at,
        suspended_at=client.suspended_at,
        suspended_by=client.suspended_by,
        suspension_reason=client.suspension_reason,
    )


@router.post("/clients/{client_id}/activate", response_model=ClientResponse)
async def activate_client(
    client_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClientResponse:
    """Activate a suspended client."""
    service = ClientAuthService(db)
    success = await service.activate_client(client_id)

    if not success:
        raise HTTPException(status_code=404, detail="Client not found")

    client = await service.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    return ClientResponse(
        client_id=client.id,
        display_name=client.display_name,
        secret_prefix=client.secret_prefix,
        client_type=client.client_type,
        status=client.status,
        rate_limit_rpm=client.rate_limit_rpm,
        rate_limit_tpm=client.rate_limit_tpm,
        created_at=client.created_at,
        updated_at=client.updated_at,
        last_used_at=client.last_used_at,
        suspended_at=client.suspended_at,
        suspended_by=client.suspended_by,
        suspension_reason=client.suspension_reason,
    )


@router.post("/clients/{client_id}/block", response_model=ClientResponse)
async def block_client(
    client_id: str,
    request: BlockRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClientResponse:
    """Permanently block a client."""
    service = ClientAuthService(db)
    success = await service.block_client(
        client_id=client_id,
        reason=request.reason,
        blocked_by=request.blocked_by,
    )

    if not success:
        raise HTTPException(status_code=404, detail="Client not found")

    client = await service.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    return ClientResponse(
        client_id=client.id,
        display_name=client.display_name,
        secret_prefix=client.secret_prefix,
        client_type=client.client_type,
        status=client.status,
        rate_limit_rpm=client.rate_limit_rpm,
        rate_limit_tpm=client.rate_limit_tpm,
        created_at=client.created_at,
        updated_at=client.updated_at,
        last_used_at=client.last_used_at,
        suspended_at=client.suspended_at,
        suspended_by=client.suspended_by,
        suspension_reason=client.suspension_reason,
    )


@router.post("/clients/{client_id}/rotate-secret", response_model=SecretRotateResponse)
async def rotate_client_secret(
    client_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SecretRotateResponse:
    """Rotate a client's secret."""
    service = ClientAuthService(db)
    new_secret = await service.rotate_secret(client_id)

    if not new_secret:
        raise HTTPException(status_code=404, detail="Client not found")

    # Get updated client for prefix
    client = await service.get_client(client_id)

    return SecretRotateResponse(
        client_id=client_id,
        secret=new_secret,
        secret_prefix=client.secret_prefix if client else new_secret[:12],
    )


# Request log endpoints
@router.get("/request-log", response_model=RequestLogResponse)
async def get_request_log(
    db: Annotated[AsyncSession, Depends(get_db)],
    client_id: str | None = Query(default=None, description="Filter by client ID"),
    status_code: int | None = Query(default=None, description="Filter by status code"),
    rejected_only: bool = Query(default=False, description="Show only rejected requests"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    days: int = Query(default=30, ge=1, le=30, description="Days of history (max 30)"),
) -> RequestLogResponse:
    """Get request log with filtering. Automatically respects 30-day retention."""
    # Calculate retention cutoff
    cutoff = datetime.now(UTC) - timedelta(days=days)

    query = select(RequestLog).where(RequestLog.created_at >= cutoff)

    if client_id:
        query = query.where(RequestLog.client_id == client_id)
    if status_code:
        query = query.where(RequestLog.status_code == status_code)
    if rejected_only:
        query = query.where(RequestLog.rejection_reason.isnot(None))

    # Get total count for pagination
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply ordering and pagination
    query = query.order_by(RequestLog.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    logs = result.scalars().all()

    # Get client display names
    client_names: dict[str, str] = {}
    client_ids = {log.client_id for log in logs if log.client_id}
    if client_ids:
        clients_result = await db.execute(select(Client).where(Client.id.in_(client_ids)))
        for client in clients_result.scalars():
            client_names[client.id] = client.display_name

    return RequestLogResponse(
        requests=[
            RequestLogEntry(
                id=log.id,
                client_id=log.client_id,
                client_display_name=client_names.get(log.client_id) if log.client_id else None,
                request_source=log.request_source,
                endpoint=log.endpoint,
                method=log.method,
                status_code=log.status_code,
                rejection_reason=log.rejection_reason,
                tokens_in=log.tokens_in,
                tokens_out=log.tokens_out,
                latency_ms=log.latency_ms,
                model=log.model,
                created_at=log.created_at,
            )
            for log in logs
        ],
        total=total,
    )
