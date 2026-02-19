"""User preferences API endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.config import UserPreference
from app.services.model_selector import QualityPreference

logger = logging.getLogger(__name__)

router = APIRouter()


class PreferencesResponse(BaseModel):
    """User preferences response."""

    model_tier_preference: str = Field(
        default="standard",
        description="Quality tier preference: economy, standard, or advanced",
    )
    gemini_auth_preference: str = Field(
        default="api_key",
        description="Gemini auth preference: oauth or api_key",
    )
    codex_auth_preference: str = Field(
        default="oauth",
        description="Codex auth preference: oauth or api_key",
    )


class PreferencesUpdate(BaseModel):
    """Update user preferences."""

    model_tier_preference: str | None = Field(
        default=None,
        pattern="^(economy|standard|advanced)$",
        description="Quality tier preference: economy, standard, or advanced",
    )
    gemini_auth_preference: str | None = Field(
        default=None,
        pattern="^(oauth|api_key)$",
        description="Gemini auth preference: oauth or api_key",
    )
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
        tier_preference = await get_preference_value(db, "model_tier_preference", "standard")
        gemini_auth = await get_preference_value(db, "gemini_auth_preference", "api_key")
        codex_auth = await get_preference_value(db, "codex_auth_preference", "oauth")
        return PreferencesResponse(
            model_tier_preference=tier_preference,
            gemini_auth_preference=gemini_auth,
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
        if preferences.model_tier_preference is not None:
            try:
                QualityPreference(preferences.model_tier_preference)
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid tier preference: {preferences.model_tier_preference}",
                ) from e
            await set_preference_value(db, "model_tier_preference", preferences.model_tier_preference)

        if preferences.gemini_auth_preference is not None:
            await set_preference_value(db, "gemini_auth_preference", preferences.gemini_auth_preference)
            # Update in-memory cache so the adapter picks it up immediately
            from app.adapters.gemini import set_gemini_auth_preference

            set_gemini_auth_preference(preferences.gemini_auth_preference)

        if preferences.codex_auth_preference is not None:
            await set_preference_value(db, "codex_auth_preference", preferences.codex_auth_preference)

        # Return current state
        return PreferencesResponse(
            model_tier_preference=await get_preference_value(db, "model_tier_preference", "standard"),
            gemini_auth_preference=await get_preference_value(db, "gemini_auth_preference", "api_key"),
            codex_auth_preference=await get_preference_value(db, "codex_auth_preference", "oauth"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update preferences: {e}")
        raise HTTPException(status_code=500, detail="Failed to update preferences") from e
