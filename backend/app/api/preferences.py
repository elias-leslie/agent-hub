"""User preferences API endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.db import get_db
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


class PreferencesUpdate(BaseModel):
    """Update user preferences."""

    model_tier_preference: str = Field(
        ...,
        pattern="^(economy|standard|advanced)$",
        description="Quality tier preference: economy, standard, or advanced",
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
        return PreferencesResponse(model_tier_preference=tier_preference)
    except Exception as e:
        logger.error(f"Failed to get preferences: {e}")
        # Return default on error
        return PreferencesResponse(model_tier_preference="standard")


@router.put("/preferences", response_model=PreferencesResponse)
async def update_preferences(
    preferences: PreferencesUpdate,
    db: AsyncSession = Depends(get_db),
) -> PreferencesResponse:
    """Update user preferences."""
    try:
        # Validate the preference value
        try:
            QualityPreference(preferences.model_tier_preference)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid tier preference: {preferences.model_tier_preference}",
            )

        await set_preference_value(db, "model_tier_preference", preferences.model_tier_preference)
        return PreferencesResponse(model_tier_preference=preferences.model_tier_preference)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update preferences: {e}")
        raise HTTPException(status_code=500, detail="Failed to update preferences")
