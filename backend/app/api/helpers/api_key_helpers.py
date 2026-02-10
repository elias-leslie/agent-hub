"""Helper functions for API key management."""

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.api_key_schemas import APIKeyResponse
from app.models import APIKey


def to_response(key: APIKey) -> APIKeyResponse:
    """Convert an APIKey model to APIKeyResponse schema."""
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


async def get_key_or_404(db: AsyncSession, key_id: int) -> APIKey:
    """Fetch an API key by ID or raise 404."""
    result = await db.execute(select(APIKey).where(APIKey.id == key_id))
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    return key


def calculate_expiration(expires_in_days: int | None) -> datetime | None:
    """Calculate expiration datetime from days."""
    if expires_in_days:
        return datetime.now(UTC) + timedelta(days=expires_in_days)
    return None
