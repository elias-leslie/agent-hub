"""API key management endpoints for OpenAI-compatible authentication."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import APIKey
from app.services.api_key_auth import generate_api_key, get_key_prefix

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


# Request/Response schemas
class APIKeyCreate(BaseModel):
    """Request to create a new API key."""

    name: str | None = Field(default=None, max_length=100, description="Friendly name for the key")
    project_id: str = Field(default="default", description="Project ID for cost tracking")
    rate_limit_rpm: int = Field(default=60, ge=1, le=1000, description="Requests per minute limit")
    rate_limit_tpm: int = Field(
        default=100000, ge=1000, le=10000000, description="Tokens per minute limit"
    )
    expires_in_days: int | None = Field(default=None, ge=1, le=365, description="Expiration in days")


class APIKeyCreateResponse(BaseModel):
    """Response when creating an API key. Contains the full key (shown once)."""

    id: int
    key: str = Field(..., description="Full API key - save this, it won't be shown again!")
    key_prefix: str = Field(..., description="Key prefix for identification")
    name: str | None
    project_id: str
    rate_limit_rpm: int
    rate_limit_tpm: int
    created_at: datetime
    expires_at: datetime | None


class APIKeyResponse(BaseModel):
    """Response for API key info (no full key)."""

    id: int
    key_prefix: str
    name: str | None
    project_id: str
    rate_limit_rpm: int
    rate_limit_tpm: int
    is_active: bool
    last_used_at: datetime | None
    created_at: datetime
    expires_at: datetime | None


class APIKeyListResponse(BaseModel):
    """Response for listing API keys."""

    keys: list[APIKeyResponse]
    total: int


class APIKeyUpdate(BaseModel):
    """Request to update an API key."""

    name: str | None = Field(default=None, max_length=100)
    rate_limit_rpm: int | None = Field(default=None, ge=1, le=1000)
    rate_limit_tpm: int | None = Field(default=None, ge=1000, le=10000000)


@router.post("", response_model=APIKeyCreateResponse, status_code=201)
async def create_api_key(
    request: APIKeyCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIKeyCreateResponse:
    """Create a new API key.

    The full key is returned only once. Save it securely - it cannot be retrieved later.
    """
    # Generate key
    full_key, key_hash = generate_api_key()
    key_prefix = get_key_prefix(full_key)

    # Calculate expiration
    expires_at = None
    if request.expires_in_days:
        from datetime import timedelta

        expires_at = datetime.utcnow() + timedelta(days=request.expires_in_days)

    # Create record
    api_key = APIKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=request.name,
        project_id=request.project_id,
        rate_limit_rpm=request.rate_limit_rpm,
        rate_limit_tpm=request.rate_limit_tpm,
        expires_at=expires_at,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return APIKeyCreateResponse(
        id=api_key.id,
        key=full_key,  # Only time the full key is returned
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
        keys=[
            APIKeyResponse(
                id=k.id,
                key_prefix=k.key_prefix,
                name=k.name,
                project_id=k.project_id,
                rate_limit_rpm=k.rate_limit_rpm,
                rate_limit_tpm=k.rate_limit_tpm,
                is_active=bool(k.is_active),
                last_used_at=k.last_used_at,
                created_at=k.created_at,
                expires_at=k.expires_at,
            )
            for k in keys
        ],
        total=len(keys),
    )


@router.get("/{key_id}", response_model=APIKeyResponse)
async def get_api_key(
    key_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIKeyResponse:
    """Get an API key by ID."""
    result = await db.execute(select(APIKey).where(APIKey.id == key_id))
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    return APIKeyResponse(
        id=key.id,
        key_prefix=key.key_prefix,
        name=key.name,
        project_id=key.project_id,
        rate_limit_rpm=key.rate_limit_rpm,
        rate_limit_tpm=key.rate_limit_tpm,
        is_active=bool(key.is_active),
        last_used_at=key.last_used_at,
        created_at=key.created_at,
        expires_at=key.expires_at,
    )


@router.patch("/{key_id}", response_model=APIKeyResponse)
async def update_api_key(
    key_id: int,
    request: APIKeyUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIKeyResponse:
    """Update an API key's settings."""
    result = await db.execute(select(APIKey).where(APIKey.id == key_id))
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    # Update fields
    updates = {}
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

    return APIKeyResponse(
        id=key.id,
        key_prefix=key.key_prefix,
        name=key.name,
        project_id=key.project_id,
        rate_limit_rpm=key.rate_limit_rpm,
        rate_limit_tpm=key.rate_limit_tpm,
        is_active=bool(key.is_active),
        last_used_at=key.last_used_at,
        created_at=key.created_at,
        expires_at=key.expires_at,
    )


@router.post("/{key_id}/revoke", response_model=APIKeyResponse)
async def revoke_api_key(
    key_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIKeyResponse:
    """Revoke an API key. This cannot be undone."""
    result = await db.execute(select(APIKey).where(APIKey.id == key_id))
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    if not key.is_active:
        raise HTTPException(status_code=400, detail="API key already revoked")

    await db.execute(update(APIKey).where(APIKey.id == key_id).values(is_active=0))
    await db.commit()
    await db.refresh(key)

    return APIKeyResponse(
        id=key.id,
        key_prefix=key.key_prefix,
        name=key.name,
        project_id=key.project_id,
        rate_limit_rpm=key.rate_limit_rpm,
        rate_limit_tpm=key.rate_limit_tpm,
        is_active=False,
        last_used_at=key.last_used_at,
        created_at=key.created_at,
        expires_at=key.expires_at,
    )


@router.post("/{key_id}/rotate", response_model=APIKeyCreateResponse)
async def rotate_api_key(
    key_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> APIKeyCreateResponse:
    """Rotate an API key - revokes the old key and creates a new one with same settings."""
    result = await db.execute(select(APIKey).where(APIKey.id == key_id))
    old_key = result.scalar_one_or_none()

    if not old_key:
        raise HTTPException(status_code=404, detail="API key not found")

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
    from sqlalchemy import delete as sql_delete

    result = await db.execute(select(APIKey).where(APIKey.id == key_id))
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    await db.execute(sql_delete(APIKey).where(APIKey.id == key_id))
    await db.commit()
