"""Access Control API endpoints for client management and request logging.

Replaces the old kill switch admin endpoints with cryptographic client auth.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access_control_helpers import client_to_response
from app.api.access_control_logs import router as logs_router
from app.api.access_control_metrics import router as metrics_router
from app.api.access_control_schemas import (
    BlockRequest,
    ClientCreateRequest,
    ClientCreateResponse,
    ClientListResponse,
    ClientResponse,
    ClientStatsResponse,
    SecretRotateResponse,
    SuspendRequest,
)
from app.db import get_db
from app.models import Client, RequestLog
from app.services.client_auth import ClientAuthService

router = APIRouter(prefix="/access-control", tags=["access-control"])
router.include_router(logs_router)
router.include_router(metrics_router)


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
        clients=[client_to_response(c) for c in clients],
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

    return client_to_response(client)


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

    return client_to_response(client)


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

    return client_to_response(client)


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

    return client_to_response(client)


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


@router.delete("/clients/{client_id}", status_code=204)
async def delete_client(
    client_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Permanently delete a client.

    This is a hard delete - the client and all associated data will be removed.
    Use suspend/block for soft removal that preserves audit history.
    """
    service = ClientAuthService(db)
    client = await service.get_client(client_id)

    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Delete the client
    await db.delete(client)
    await db.commit()
