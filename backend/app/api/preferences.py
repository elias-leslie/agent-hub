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
    gemini_vertex_project: str = Field(
        default="",
        description="GCP project ID for Vertex AI (required for OAuth mode)",
    )
    codex_auth_preference: str = Field(
        default="oauth",
        description="Codex auth preference: oauth or api_key",
    )
    heartbeat_interval_minutes: int = Field(
        default=60,
        description="Johnny heartbeat interval in minutes (0 = disabled)",
    )
    tts_voice: str = Field(
        default="en-US-AriaNeural",
        description="Selected TTS voice ID",
    )
    tts_enabled: bool = Field(
        default=False,
        description="Whether auto-speak is enabled for responses",
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
    gemini_vertex_project: str | None = Field(
        default=None,
        description="GCP project ID for Vertex AI (required for OAuth mode)",
    )
    codex_auth_preference: str | None = Field(
        default=None,
        pattern="^(oauth|api_key)$",
        description="Codex auth preference: oauth or api_key",
    )
    heartbeat_interval_minutes: int | None = Field(
        default=None,
        ge=0,
        le=1440,
        description="Johnny heartbeat interval in minutes (0 = disabled, max 1440 = 24h)",
    )
    tts_voice: str | None = Field(
        default=None,
        description="Selected TTS voice ID (e.g. en-US-AriaNeural)",
    )
    tts_enabled: bool | None = Field(
        default=None,
        description="Whether auto-speak is enabled for responses",
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
        gemini_project = await get_preference_value(db, "gemini_vertex_project", "")
        codex_auth = await get_preference_value(db, "codex_auth_preference", "oauth")
        heartbeat = await get_preference_value(db, "heartbeat_interval_minutes", "60")
        tts_voice = await get_preference_value(db, "tts_voice", "en-US-AriaNeural")
        tts_enabled = await get_preference_value(db, "tts_enabled", "false")
        return PreferencesResponse(
            model_tier_preference=tier_preference,
            gemini_auth_preference=gemini_auth,
            gemini_vertex_project=gemini_project,
            codex_auth_preference=codex_auth,
            heartbeat_interval_minutes=int(heartbeat),
            tts_voice=tts_voice,
            tts_enabled=tts_enabled.lower() == "true",
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
            # Update in-memory cache and invalidate adapter so it's recreated with new auth mode
            from app.adapters.gemini import set_gemini_auth_preference
            from app.api.complete.helpers_adapters import invalidate_adapter

            set_gemini_auth_preference(preferences.gemini_auth_preference)
            invalidate_adapter("gemini")

        if preferences.gemini_vertex_project is not None:
            await set_preference_value(db, "gemini_vertex_project", preferences.gemini_vertex_project)
            from app.adapters.gemini import set_gemini_vertex_project
            from app.api.complete.helpers_adapters import invalidate_adapter

            set_gemini_vertex_project(preferences.gemini_vertex_project)
            invalidate_adapter("gemini")

        if preferences.codex_auth_preference is not None:
            await set_preference_value(db, "codex_auth_preference", preferences.codex_auth_preference)
            from app.api.complete.helpers_adapters import invalidate_adapter

            invalidate_adapter("codex")

        if preferences.heartbeat_interval_minutes is not None:
            await set_preference_value(
                db, "heartbeat_interval_minutes", str(preferences.heartbeat_interval_minutes)
            )

        if preferences.tts_voice is not None:
            await set_preference_value(db, "tts_voice", preferences.tts_voice)

        if preferences.tts_enabled is not None:
            await set_preference_value(db, "tts_enabled", str(preferences.tts_enabled).lower())

        # Return current state
        heartbeat_val = await get_preference_value(db, "heartbeat_interval_minutes", "60")
        tts_voice_val = await get_preference_value(db, "tts_voice", "en-US-AriaNeural")
        tts_enabled_val = await get_preference_value(db, "tts_enabled", "false")
        return PreferencesResponse(
            model_tier_preference=await get_preference_value(db, "model_tier_preference", "standard"),
            gemini_auth_preference=await get_preference_value(db, "gemini_auth_preference", "api_key"),
            gemini_vertex_project=await get_preference_value(db, "gemini_vertex_project", ""),
            codex_auth_preference=await get_preference_value(db, "codex_auth_preference", "oauth"),
            heartbeat_interval_minutes=int(heartbeat_val),
            tts_voice=tts_voice_val,
            tts_enabled=tts_enabled_val.lower() == "true",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update preferences: {e}")
        raise HTTPException(status_code=500, detail="Failed to update preferences") from e
