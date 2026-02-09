"""Client management endpoints for Access Control API."""

import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access_control_helpers import client_to_response
from app.api.access_control_schemas import (
    BlockRequest,
    ClientCreateRequest,
    ClientCreateResponse,
    ClientListResponse,
    ClientResponse,
    ClientUpdateRequest,
    SecretRotateResponse,
    SuspendRequest,
)
from app.db import get_db
from app.models import Client
from app.services.client_auth import ClientAuthService

router = APIRouter()


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


@router.patch("/clients/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: str,
    request: ClientUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClientResponse:
    """Update client settings (display name, rate limits, allowed projects)."""
    from app.middleware.access_control import invalidate_client_cache

    service = ClientAuthService(db)
    client = await service.get_client(client_id)

    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Update fields if provided
    if request.display_name is not None:
        client.display_name = request.display_name
    if request.rate_limit_rpm is not None:
        client.rate_limit_rpm = request.rate_limit_rpm
    if request.rate_limit_tpm is not None:
        client.rate_limit_tpm = request.rate_limit_tpm
    if request.allowed_projects is not None:
        # Convert list to JSON string for storage
        client.allowed_projects = json.dumps(request.allowed_projects)

    await db.commit()
    await db.refresh(client)

    # Invalidate cache so changes take effect immediately
    invalidate_client_cache(client_id)

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
