"""Credentials API - CRUD operations for encrypted credentials."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.credential_manager import get_credential_manager
from app.storage.credentials import (
    store_credential_async,
    get_credential_by_id_async,
    update_credential_async,
    delete_credential_async,
    list_credentials_async,
    decrypt_value,
    EncryptionError,
)

router = APIRouter()


# Valid credential types
VALID_CREDENTIAL_TYPES = {"api_key", "oauth_token", "refresh_token"}
VALID_PROVIDERS = {"claude", "gemini"}


def mask_value(value: str) -> str:
    """Mask a credential value for display."""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


# Request/Response schemas
class CredentialCreate(BaseModel):
    """Request body for creating a credential."""

    provider: str = Field(..., description="Provider: claude or gemini")
    credential_type: str = Field(..., description="Type: api_key, oauth_token, refresh_token")
    value: str = Field(..., min_length=1, description="Credential value (will be encrypted)")


class CredentialUpdate(BaseModel):
    """Request body for updating a credential."""

    value: str = Field(..., min_length=1, description="New credential value")


class CredentialResponse(BaseModel):
    """Response body for credential operations (masked value)."""

    id: int
    provider: str
    credential_type: str
    value_masked: str = Field(..., description="Masked credential value")
    created_at: datetime
    updated_at: datetime


class CredentialListResponse(BaseModel):
    """Response body for listing credentials."""

    credentials: list[CredentialResponse]
    total: int


@router.post("/credentials", response_model=CredentialResponse, status_code=201)
async def create_credential(
    request: CredentialCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CredentialResponse:
    """Store a new encrypted credential."""
    if request.provider not in VALID_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider. Must be one of: {', '.join(VALID_PROVIDERS)}",
        )
    if request.credential_type not in VALID_CREDENTIAL_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid credential_type. Must be one of: {', '.join(VALID_CREDENTIAL_TYPES)}",
        )

    try:
        credential = await store_credential_async(
            db,
            provider=request.provider,
            credential_type=request.credential_type,
            value=request.value,
        )
        # Update cache
        get_credential_manager().set(request.provider, request.credential_type, request.value)
    except EncryptionError as e:
        raise HTTPException(status_code=500, detail=f"Encryption error: {e}") from e

    return CredentialResponse(
        id=credential.id,
        provider=credential.provider,
        credential_type=credential.credential_type,
        value_masked=mask_value(request.value),
        created_at=credential.created_at,
        updated_at=credential.updated_at,
    )


@router.get("/credentials", response_model=CredentialListResponse)
async def list_credentials(
    db: Annotated[AsyncSession, Depends(get_db)],
    provider: Annotated[str | None, Query(description="Filter by provider")] = None,
) -> CredentialListResponse:
    """List all credentials with masked values."""
    credentials = await list_credentials_async(db, provider=provider)

    responses = []
    for cred in credentials:
        try:
            decrypted = decrypt_value(cred.value_encrypted)
            masked = mask_value(decrypted)
        except EncryptionError:
            masked = "***ERROR***"

        responses.append(
            CredentialResponse(
                id=cred.id,
                provider=cred.provider,
                credential_type=cred.credential_type,
                value_masked=masked,
                created_at=cred.created_at,
                updated_at=cred.updated_at,
            )
        )

    return CredentialListResponse(
        credentials=responses,
        total=len(responses),
    )


@router.get("/credentials/{credential_id}", response_model=CredentialResponse)
async def get_credential(
    credential_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CredentialResponse:
    """Get a credential by ID (value masked)."""
    credential = await get_credential_by_id_async(db, credential_id)
    if not credential:
        raise HTTPException(status_code=404, detail="Credential not found")

    try:
        decrypted = decrypt_value(credential.value_encrypted)
        masked = mask_value(decrypted)
    except EncryptionError:
        masked = "***ERROR***"

    return CredentialResponse(
        id=credential.id,
        provider=credential.provider,
        credential_type=credential.credential_type,
        value_masked=masked,
        created_at=credential.created_at,
        updated_at=credential.updated_at,
    )


@router.put("/credentials/{credential_id}", response_model=CredentialResponse)
async def update_credential(
    credential_id: int,
    request: CredentialUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CredentialResponse:
    """Update a credential's value."""
    try:
        credential = await update_credential_async(db, credential_id, request.value)
    except EncryptionError as e:
        raise HTTPException(status_code=500, detail=f"Encryption error: {e}") from e

    if not credential:
        raise HTTPException(status_code=404, detail="Credential not found")

    # Update cache
    get_credential_manager().set(credential.provider, credential.credential_type, request.value)

    return CredentialResponse(
        id=credential.id,
        provider=credential.provider,
        credential_type=credential.credential_type,
        value_masked=mask_value(request.value),
        created_at=credential.created_at,
        updated_at=credential.updated_at,
    )


@router.delete("/credentials/{credential_id}", status_code=204)
async def delete_credential(
    credential_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Delete a credential."""
    # Get credential first to know provider/type for cache removal
    credential = await get_credential_by_id_async(db, credential_id)
    if not credential:
        raise HTTPException(status_code=404, detail="Credential not found")

    deleted = await delete_credential_async(db, credential_id)
    if deleted:
        # Remove from cache
        get_credential_manager().remove(credential.provider, credential.credential_type)
