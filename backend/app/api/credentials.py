"""Credentials API - CRUD operations for encrypted credentials."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.credential_manager import get_credential_manager
from app.services.system_credentials import is_system_credential_provider
from app.storage.credentials import (
    EncryptionError,
    decrypt_value,
    delete_credential_async,
    get_credential_by_id_async,
    list_credentials_async,
    store_credential_async,
    update_credential_async,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# Valid credential types
VALID_CREDENTIAL_TYPES = {"api_key", "oauth_token", "refresh_token", "account_id"}

CLAUDE_CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"


def _is_visible_credential_provider(provider: str) -> bool:
    """Return whether a credential provider should be exposed via the public API."""
    return not is_system_credential_provider(provider)


def _require_visible_provider(provider: str) -> None:
    """Block public CRUD access to hidden system-managed credential rows."""
    if not _is_visible_credential_provider(provider):
        raise HTTPException(status_code=404, detail="Credential not found")


def mask_value(value: str) -> str:
    """Mask a credential value for display."""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


def _build_credential_response(cred: Any, masked: str) -> CredentialResponse:
    """Build a CredentialResponse from a DB credential object and masked value."""
    return CredentialResponse(
        id=cred.id,
        provider=cred.provider,
        credential_type=cred.credential_type,
        value_masked=masked,
        created_at=cred.created_at,
        updated_at=cred.updated_at,
    )


def _decrypt_masked(value_encrypted: str) -> str:
    """Decrypt an encrypted credential value and return its masked form."""
    try:
        return mask_value(decrypt_value(value_encrypted))
    except EncryptionError:
        return "***ERROR***"


# Request/Response schemas
class CredentialCreate(BaseModel):
    """Request body for creating a credential."""

    provider: str = Field(..., max_length=100, description="Provider name (claude, cloudflare, codex, deepseek, gemini, local, minimax, moonshot, nvidia, openrouter, openai, xai, zhipu)")
    credential_type: str = Field(..., max_length=50, description="Type: api_key, oauth_token, refresh_token")
    value: str = Field(..., min_length=1, max_length=10000, description="Credential value (will be encrypted)")


class CredentialUpdate(BaseModel):
    """Request body for updating a credential."""

    value: str = Field(..., min_length=1, max_length=10000, description="New credential value")


class CredentialResponse(BaseModel):
    """Response body for credential operations (masked value)."""

    id: int
    provider: str
    credential_type: str
    value_masked: str = Field(..., description="Masked credential value")
    created_at: datetime
    updated_at: datetime


class ClaudeOAuthStatus(BaseModel):
    """Read-only status of Claude Code OAuth token."""

    status: str = Field(..., description="valid, expired, or missing")
    expires_at: datetime | None = Field(default=None, description="Token expiry time")
    expires_in_seconds: int | None = Field(default=None, description="Seconds until expiry")
    scopes: list[str] = Field(default_factory=list)
    subscription_type: str | None = Field(default=None)
    token_prefix: str | None = Field(default=None, description="First 12 chars of access token")


class SetPrimaryCredentialResponse(BaseModel):
    """Response body for setting primary credential."""

    success: bool
    provider: str
    primary_credential_id: int


@router.post("/credentials", response_model=CredentialResponse, status_code=201)
async def create_credential(
    request: CredentialCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CredentialResponse:
    """Store a new encrypted credential."""
    from app.adapters.registry import list_providers

    if is_system_credential_provider(request.provider):
        raise HTTPException(status_code=400, detail="System-managed credential providers are not writable via this API")

    valid_providers = set(list_providers())
    if request.provider not in valid_providers:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider. Must be one of: {', '.join(sorted(valid_providers))}",
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
        get_credential_manager().set(request.provider, request.credential_type, request.value)
    except EncryptionError as e:
        raise HTTPException(status_code=500, detail=f"Encryption error: {e}") from e

    return _build_credential_response(credential, mask_value(request.value))


@router.get("/credentials", response_model=dict[str, Any])
async def list_credentials(
    db: Annotated[AsyncSession, Depends(get_db)],
    provider: Annotated[str | None, Query(description="Filter by provider")] = None,
) -> dict[str, Any]:
    """List all credentials with masked values."""
    credentials = await list_credentials_async(db, provider=provider)
    credentials = [cred for cred in credentials if _is_visible_credential_provider(cred.provider)]

    responses = [
        _build_credential_response(cred, _decrypt_masked(cred.value_encrypted))
        for cred in credentials
    ]

    return {"credentials": [r.model_dump() for r in responses], "total": len(responses)}


@router.get("/credentials/claude-oauth-status", response_model=ClaudeOAuthStatus)
async def get_claude_oauth_status() -> ClaudeOAuthStatus:
    """Check Claude Code OAuth token status (read-only).

    Reads ~/.claude/.credentials.json without modifying it.
    """
    if not CLAUDE_CREDENTIALS_PATH.exists():
        return ClaudeOAuthStatus(status="missing")

    try:
        data = json.loads(CLAUDE_CREDENTIALS_PATH.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to read Claude credentials: {e}")
        return ClaudeOAuthStatus(status="missing")

    oauth = data.get("claudeAiOauth")
    if not oauth or not oauth.get("accessToken"):
        return ClaudeOAuthStatus(status="missing")

    expires_at_ms = oauth.get("expiresAt", 0)
    now_ms = int(datetime.now().timestamp() * 1000)
    expires_at = datetime.fromtimestamp(expires_at_ms / 1000) if expires_at_ms else None
    expires_in = int((expires_at_ms - now_ms) / 1000) if expires_at_ms else None
    access_token = oauth.get("accessToken", "")
    token_prefix = access_token[:12] + "..." if len(access_token) > 12 else None

    return ClaudeOAuthStatus(
        status="valid" if expires_at_ms > now_ms else "expired",
        expires_at=expires_at,
        expires_in_seconds=expires_in,
        scopes=oauth.get("scopes", []),
        subscription_type=oauth.get("subscriptionType"),
        token_prefix=token_prefix,
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
    _require_visible_provider(credential.provider)
    return _build_credential_response(credential, _decrypt_masked(credential.value_encrypted))


@router.put("/credentials/{credential_id}", response_model=CredentialResponse)
async def update_credential(
    credential_id: int,
    request: CredentialUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CredentialResponse:
    """Update a credential's value."""
    existing_cred = await get_credential_by_id_async(db, credential_id)
    if not existing_cred:
        raise HTTPException(status_code=404, detail="Credential not found")
    _require_visible_provider(existing_cred.provider)

    try:
        old_value: str | None = decrypt_value(existing_cred.value_encrypted)
    except Exception:
        logger.debug("Failed to decrypt old credential value for diff", exc_info=True)
        old_value = None

    try:
        credential = await update_credential_async(db, credential_id, request.value)
    except EncryptionError as e:
        raise HTTPException(status_code=500, detail=f"Encryption error: {e}") from e

    if not credential:
        raise HTTPException(status_code=404, detail="Credential not found")

    cred_mgr = get_credential_manager()
    if old_value is not None:
        cred_mgr.replace_value(credential.provider, credential.credential_type, old_value, request.value)
    else:
        cred_mgr.set(credential.provider, credential.credential_type, request.value)

    return _build_credential_response(credential, mask_value(request.value))


@router.delete("/credentials/{credential_id}", status_code=204)
async def delete_credential(
    credential_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Delete a credential."""
    credential = await get_credential_by_id_async(db, credential_id)
    if not credential:
        raise HTTPException(status_code=404, detail="Credential not found")
    _require_visible_provider(credential.provider)

    try:
        value: str | None = decrypt_value(credential.value_encrypted)
    except EncryptionError:
        value = None

    deleted = await delete_credential_async(db, credential_id)
    if deleted:
        cred_mgr = get_credential_manager()
        if value:
            cred_mgr.remove_value(credential.provider, credential.credential_type, value)
        else:
            cred_mgr.remove(credential.provider, credential.credential_type)


async def _swap_credentials_and_refresh_cache(
    db: AsyncSession,
    primary: Any,
    target: Any,
) -> int:
    """Swap primary and target api_key values, refresh cache, return new primary ID."""
    try:
        primary_value = decrypt_value(primary.value_encrypted)
        target_value = decrypt_value(target.value_encrypted)
    except EncryptionError as e:
        raise HTTPException(status_code=500, detail=f"Encryption error: {e}") from e

    try:
        await update_credential_async(db, primary.id, target_value)
        await update_credential_async(db, target.id, primary_value)
    except EncryptionError as e:
        raise HTTPException(status_code=500, detail=f"Encryption error: {e}") from e

    refreshed = await list_credentials_async(db, provider=target.provider)
    ordered_keys: list[str] = []
    for cred in refreshed:
        if cred.credential_type != "api_key":
            continue
        try:
            ordered_keys.append(decrypt_value(cred.value_encrypted))
        except EncryptionError:
            continue

    get_credential_manager().set_api_keys(target.provider, ordered_keys)

    new_primary_id = primary.id
    for cred in refreshed:
        if cred.credential_type == "api_key":
            new_primary_id = cred.id
            break
    return new_primary_id


@router.post("/credentials/{credential_id}/set-primary", response_model=SetPrimaryCredentialResponse)
async def set_primary_credential(
    credential_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SetPrimaryCredentialResponse:
    """Set an API key credential as primary by swapping with current first key.

    Primary key is defined by lowest credential ID in provider/api_key order.
    """
    target = await get_credential_by_id_async(db, credential_id)
    if not target:
        raise HTTPException(status_code=404, detail="Credential not found")
    _require_visible_provider(target.provider)

    if target.credential_type != "api_key":
        raise HTTPException(status_code=400, detail="Only api_key credentials can be made primary")

    creds = await list_credentials_async(db, provider=target.provider)
    api_keys = [c for c in creds if c.credential_type == "api_key"]
    if not api_keys:
        raise HTTPException(status_code=400, detail="No API keys found for provider")

    primary = api_keys[0]
    if primary.id == target.id:
        return SetPrimaryCredentialResponse(
            success=True, provider=target.provider, primary_credential_id=target.id
        )

    new_primary_id = await _swap_credentials_and_refresh_cache(db, primary, target)
    return SetPrimaryCredentialResponse(
        success=True,
        provider=target.provider,
        primary_credential_id=new_primary_id,
    )
