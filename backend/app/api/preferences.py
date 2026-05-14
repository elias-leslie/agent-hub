"""User preferences API endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.config import UserPreference

logger = logging.getLogger(__name__)

router = APIRouter()


class PreferencesResponse(BaseModel):
    """User preferences response."""

    codex_auth_preference: str = Field(
        default="oauth",
        description="Codex auth preference: oauth or api_key",
    )


class PreferencesUpdate(BaseModel):
    """Update user preferences."""

    codex_auth_preference: str | None = Field(
        default=None,
        pattern="^(oauth|api_key)$",
        description="Codex auth preference: oauth or api_key",
    )


async def get_preference_value(db: AsyncSession, key: str, default: str = "standard") -> str:
    """Get a preference value from the database."""
    from sqlalchemy import select

    result = await db.execute(select(UserPreference).where(UserPreference.key == key))
    pref = result.scalar_one_or_none()
    return pref.value if pref else default


async def set_preference_value(db: AsyncSession, key: str, value: str) -> None:
    """Set a preference value in the database."""
    from sqlalchemy import select

    result = await db.execute(select(UserPreference).where(UserPreference.key == key))
    pref = result.scalar_one_or_none()

    if pref:
        pref.value = value
    else:
        pref = UserPreference(key=key, value=value)
        db.add(pref)

    await db.commit()


@router.get("/preferences", response_model=PreferencesResponse)
async def get_preferences(db: AsyncSession = Depends(get_db)) -> PreferencesResponse:
    """Get user preferences."""
    try:
        codex_auth = await get_preference_value(db, "codex_auth_preference", "oauth")
        return PreferencesResponse(
            codex_auth_preference=codex_auth,
        )
    except Exception as e:
        logger.error(f"Failed to get preferences: {e}")
        return PreferencesResponse()


@router.put("/preferences", response_model=PreferencesResponse)
async def update_preferences(
    preferences: PreferencesUpdate,
    db: AsyncSession = Depends(get_db),
) -> PreferencesResponse:
    """Update user preferences. Only provided fields are updated."""
    try:
        from app.routing.registry import invalidate as invalidate_adapter

        if preferences.codex_auth_preference is not None:
            await set_preference_value(db, "codex_auth_preference", preferences.codex_auth_preference)
            invalidate_adapter("codex")

        # Return current state
        return PreferencesResponse(
            codex_auth_preference=await get_preference_value(db, "codex_auth_preference", "oauth"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update preferences: {e}")
        raise HTTPException(status_code=500, detail="Failed to update preferences") from e
