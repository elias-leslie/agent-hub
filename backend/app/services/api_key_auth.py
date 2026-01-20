"""API key authentication for OpenAI-compatible endpoints.

Provides:
- API key generation and validation
- Rate limiting per key
- Project-based cost tracking
"""

import hashlib
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import APIKey

# API key prefix for Agent Hub keys
KEY_PREFIX = "sk-ah-"


@dataclass
class RateLimitState:
    """Track rate limit state for an API key."""

    request_count: int = 0
    token_count: int = 0
    window_start: float = 0.0


# In-memory rate limit tracking (would use Redis in production)
_rate_limits: dict[str, RateLimitState] = defaultdict(RateLimitState)


def generate_api_key() -> tuple[str, str]:
    """Generate a new API key.

    Returns:
        Tuple of (full_key, key_hash)
        The full key is returned once and should be shown to the user.
        The hash is stored in the database.
    """
    # Generate 32 random bytes (256 bits) -> 43 chars base64
    random_part = secrets.token_urlsafe(32)
    full_key = f"{KEY_PREFIX}{random_part}"
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    return full_key, key_hash


def hash_api_key(api_key: str) -> str:
    """Hash an API key for lookup."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def get_key_prefix(api_key: str) -> str:
    """Get the display prefix for an API key."""
    # "sk-ah-" (6) + first 8 chars of random part
    return api_key[:14] if len(api_key) >= 14 else api_key


async def validate_api_key(
    db: AsyncSession,
    api_key: str,
) -> APIKey | None:
    """Validate an API key and return the key record if valid.

    Returns None if:
    - Key not found
    - Key is revoked (is_active=0)
    - Key is expired
    """
    key_hash = hash_api_key(api_key)

    result = await db.execute(select(APIKey).where(APIKey.key_hash == key_hash))
    key_record = result.scalar_one_or_none()

    if not key_record:
        return None

    # Check if revoked
    if not key_record.is_active:
        return None

    # Check if expired
    if key_record.expires_at and key_record.expires_at < datetime.now(UTC):
        return None

    return key_record


async def update_key_last_used(db: AsyncSession, key_id: int) -> None:
    """Update the last_used_at timestamp for an API key."""
    await db.execute(
        update(APIKey).where(APIKey.id == key_id).values(last_used_at=datetime.now(UTC))
    )
    await db.commit()


def check_rate_limit(
    key_hash: str,
    rpm_limit: int,
    tpm_limit: int,
    token_count: int = 0,
) -> tuple[bool, str | None]:
    """Check if a request is within rate limits.

    Args:
        key_hash: Hash of the API key
        rpm_limit: Requests per minute limit
        tpm_limit: Tokens per minute limit
        token_count: Estimated tokens for this request

    Returns:
        Tuple of (is_allowed, error_message)
    """
    now = time.time()
    state = _rate_limits[key_hash]

    # Reset window if expired (1 minute window)
    if now - state.window_start >= 60:
        state.request_count = 0
        state.token_count = 0
        state.window_start = now

    # Check request limit
    if state.request_count >= rpm_limit:
        retry_after = int(60 - (now - state.window_start))
        return (
            False,
            f"Rate limit exceeded: {rpm_limit} requests/minute. Retry after {retry_after}s",
        )

    # Check token limit
    if state.token_count + token_count > tpm_limit:
        retry_after = int(60 - (now - state.window_start))
        return False, f"Token limit exceeded: {tpm_limit} tokens/minute. Retry after {retry_after}s"

    # Update counters
    state.request_count += 1
    state.token_count += token_count

    return True, None


def update_token_count(key_hash: str, tokens: int) -> None:
    """Update token count after a request completes."""
    if key_hash in _rate_limits:
        _rate_limits[key_hash].token_count += tokens


@dataclass
class AuthenticatedKey:
    """Result of successful API key authentication."""

    key_id: int
    key_hash: str
    project_id: str
    rate_limit_rpm: int
    rate_limit_tpm: int


async def require_api_key(
    authorization: Annotated[str | None, Header()] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> AuthenticatedKey | None:
    """FastAPI dependency for optional API key authentication.

    If no Authorization header is provided, returns None (anonymous access).
    If provided but invalid, raises HTTPException.
    If valid, returns AuthenticatedKey with project info.

    Note: Set required=True in your endpoint if authentication is mandatory.
    """
    if not authorization:
        return None

    # Parse Bearer token
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "Invalid authorization header format. Expected 'Bearer <api-key>'",
                    "type": "authentication_error",
                    "code": "invalid_auth_header",
                }
            },
        )

    api_key = authorization[7:]  # Remove "Bearer " prefix

    # Validate the key
    if not db:
        # No database connection - allow anonymous
        return None

    key_record = await validate_api_key(db, api_key)
    if not key_record:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "Invalid API key",
                    "type": "authentication_error",
                    "code": "invalid_api_key",
                }
            },
        )

    key_hash = hash_api_key(api_key)

    # Check rate limits (estimate 1000 tokens per request for pre-check)
    is_allowed, error_msg = check_rate_limit(
        key_hash, key_record.rate_limit_rpm, key_record.rate_limit_tpm, 1000
    )
    if not is_allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "error": {
                    "message": error_msg,
                    "type": "rate_limit_error",
                    "code": "rate_limit_exceeded",
                }
            },
        )

    # Update last used (fire and forget - don't await)
    await update_key_last_used(db, key_record.id)

    return AuthenticatedKey(
        key_id=key_record.id,
        key_hash=key_hash,
        project_id=key_record.project_id,
        rate_limit_rpm=key_record.rate_limit_rpm,
        rate_limit_tpm=key_record.rate_limit_tpm,
    )


async def require_api_key_strict(
    authorization: Annotated[str | None, Header()] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> AuthenticatedKey:
    """FastAPI dependency for required API key authentication.

    Raises HTTPException if no valid API key is provided.
    """
    result = await require_api_key(authorization, db)
    if result is None:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "API key required. Use 'Authorization: Bearer <api-key>'",
                    "type": "authentication_error",
                    "code": "api_key_required",
                }
            },
        )
    return result
