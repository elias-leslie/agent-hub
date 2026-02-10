"""API key management endpoints for OpenAI-compatible authentication."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sql_delete
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.helpers.api_key_helpers import calculate_expiration, get_key_or_404, to_response
from app.api.schemas.api_key_schemas import (
    APIKeyCreate,
    APIKeyCreateResponse,
    APIKeyListResponse,
    APIKeyResponse,
    APIKeyUpdate,
)
from app.db import get_db
from app.models import APIKey
from app.services.api_key_auth import generate_api_key, get_key_prefix

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.post("", response_model=APIKeyCreateResponse, status_code=201)
async def create_api_key(
    request: APIKeyCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIKeyCreateResponse:
    """Create a new API key.

    The full key is returned only once. Save it securely - it cannot be retrieved later.
    """
    full_key, key_hash = generate_api_key()
    key_prefix = get_key_prefix(full_key)

    api_key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=request.name,
        project_id=request.project_id,
        rate_limit_rpm=request.rate_limit_rpm,
        rate_limit_tpm=request.rate_limit_tpm,
        expires_at=calculate_expiration(request.expires_in_days),
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return APIKeyCreateResponse(
        id=api_key.id,
        key=full_key,
        key_prefix=key_prefix,
        name=api_key.name,
        project_id=api_key.project_id,
        rate_limit_rpm=api_key.rate_limit_rpm,
        rate_limit_tpm=api_key.rate_limit_tpm,
        created_at=api_key.created_at,
        expires_at=api_key.expires_at,
    )


@router.get("", response_model=APIKeyListResponse)
async def list_api_keys(
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: str | None = None,
    include_revoked: bool = False,
) -> APIKeyListResponse:
    """List all API keys, optionally filtered by project."""
    query = select(APIKey)

    if project_id:
        query = query.where(APIKey.project_id == project_id)
    if not include_revoked:
        query = query.where(APIKey.is_active == 1)

    query = query.order_by(APIKey.created_at.desc())
    result = await db.execute(query)
    keys = result.scalars().all()

    return APIKeyListResponse(
        keys=[to_response(k) for k in keys],
        total=len(keys),
    )


@router.get("/{key_id}", response_model=APIKeyResponse)
async def get_api_key(
    key_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIKeyResponse:
    """Get an API key by ID."""
    key = await get_key_or_404(db, key_id)
    return to_response(key)


@router.patch("/{key_id}", response_model=APIKeyResponse)
async def update_api_key(
    key_id: int,
    request: APIKeyUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIKeyResponse:
    """Update an API key's settings."""
    key = await get_key_or_404(db, key_id)

    updates: dict[str, str | int] = {}
    if request.name is not None:
        updates["name"] = request.name
    if request.rate_limit_rpm is not None:
        updates["rate_limit_rpm"] = request.rate_limit_rpm
    if request.rate_limit_tpm is not None:
        updates["rate_limit_tpm"] = request.rate_limit_tpm

    if updates:
        await db.execute(update(APIKey).where(APIKey.id == key_id).values(**updates))
        await db.commit()
        await db.refresh(key)

    return to_response(key)


@router.post("/{key_id}/revoke", response_model=APIKeyResponse)
async def revoke_api_key(
    key_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIKeyResponse:
    """Revoke an API key. This cannot be undone."""
    key = await get_key_or_404(db, key_id)

    if not key.is_active:
        raise HTTPException(status_code=400, detail="API key already revoked")

    await db.execute(update(APIKey).where(APIKey.id == key_id).values(is_active=0))
    await db.commit()
    await db.refresh(key)

    return to_response(key)


@router.post("/{key_id}/rotate", response_model=APIKeyCreateResponse)
async def rotate_api_key(
    key_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIKeyCreateResponse:
    """Rotate an API key - revokes the old key and creates a new one with same settings."""
    old_key = await get_key_or_404(db, key_id)

    if not old_key.is_active:
        raise HTTPException(status_code=400, detail="Cannot rotate a revoked key")

    # Revoke old key
    await db.execute(update(APIKey).where(APIKey.id == key_id).values(is_active=0))

    # Generate new key with same settings
    full_key, key_hash = generate_api_key()
    key_prefix = get_key_prefix(full_key)

    new_key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=old_key.name,
        project_id=old_key.project_id,
        rate_limit_rpm=old_key.rate_limit_rpm,
        rate_limit_tpm=old_key.rate_limit_tpm,
        expires_at=old_key.expires_at,
    )
    db.add(new_key)
    await db.commit()
    await db.refresh(new_key)

    return APIKeyCreateResponse(
        id=new_key.id,
        key=full_key,
        key_prefix=key_prefix,
        name=new_key.name,
        project_id=new_key.project_id,
        rate_limit_rpm=new_key.rate_limit_rpm,
        rate_limit_tpm=new_key.rate_limit_tpm,
        created_at=new_key.created_at,
        expires_at=new_key.expires_at,
    )


@router.delete("/{key_id}", status_code=204)
async def delete_api_key(
    key_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Permanently delete an API key. Use revoke for soft-delete."""
    await get_key_or_404(db, key_id)
    await db.execute(sql_delete(APIKey).where(APIKey.id == key_id))
    await db.commit()
