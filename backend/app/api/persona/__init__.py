"""Persona API — first-class identity management for the concierge persona."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.persona_service import get_or_create_persona

from .activity import router as _activity_router
from .constants import PROTECTED_TEXT_FIELDS
from .helpers import apply_shrinkage_protection, commit_and_refresh, persona_to_response
from .journal import router as _journal_router
from .schemas import (
    PersonaPersonalityResponse,
    PersonaPersonalityUpdate,
    PersonaResponse,
    PersonaUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/persona", tags=["persona"])


@router.get("", response_model=PersonaResponse)
async def get_persona(db: AsyncSession = Depends(get_db)) -> PersonaResponse:
    """Get the full persona configuration."""
    persona = await get_or_create_persona(db)
    return persona_to_response(persona)


@router.put("", response_model=PersonaResponse)
async def update_persona(
    update: PersonaUpdate,
    db: AsyncSession = Depends(get_db),
) -> PersonaResponse:
    """Update persona fields (partial update — only provided fields are changed)."""
    persona = await get_or_create_persona(db)
    update_data = update.model_dump(exclude_unset=True)

    if not update_data:
        return persona_to_response(persona)

    for field in PROTECTED_TEXT_FIELDS:
        if field in update_data and update_data[field] is not None:
            apply_shrinkage_protection(persona, field, update_data[field], update_data)

    for field, value in update_data.items():
        setattr(persona, field, value)

    persona.version += 1
    await commit_and_refresh(db, persona)

    logger.info("Persona updated: fields=%s", list(update_data.keys()))
    return persona_to_response(persona)


@router.post("/reset-onboarding", response_model=PersonaResponse)
async def reset_onboarding(db: AsyncSession = Depends(get_db)) -> PersonaResponse:
    """Reset onboarding so bootstrap instructions are injected on next conversation.

    Clears user_context and resets onboarding_attempts so Jenny starts truly
    fresh — no stale context that could make her act mid-onboarding.
    """
    persona = await get_or_create_persona(db)
    persona.onboarding_complete = False
    persona.onboarding_phase = "not_started"
    persona.onboarding_attempts = 0
    persona.user_context = None
    persona.version += 1
    await commit_and_refresh(db, persona)
    logger.info("Persona onboarding fully reset (phase → not_started, context cleared)")
    return persona_to_response(persona)


@router.get("/personality", response_model=PersonaPersonalityResponse)
async def get_personality(db: AsyncSession = Depends(get_db)) -> PersonaPersonalityResponse:
    """Get just the personality document (for agent self-read)."""
    persona = await get_or_create_persona(db)
    return PersonaPersonalityResponse(
        personality=persona.personality,
        version=persona.version,
    )


@router.put("/personality", response_model=PersonaPersonalityResponse)
async def update_personality(
    update: PersonaPersonalityUpdate,
    db: AsyncSession = Depends(get_db),
) -> PersonaPersonalityResponse:
    """Update the personality document (for agent self-modification)."""
    persona = await get_or_create_persona(db)

    # Apply shrinkage protection — same guard used by PUT /api/persona for text fields
    update_data: dict = {"personality": update.personality}
    apply_shrinkage_protection(persona, "personality", update.personality, update_data)
    persona.personality = update_data["personality"]

    persona.version += 1
    await commit_and_refresh(db, persona)

    reason_log = f" reason={update.reason}" if update.reason else ""
    logger.info("Personality updated: version=%d%s", persona.version, reason_log)
    return PersonaPersonalityResponse(
        personality=persona.personality,
        version=persona.version,
    )


router.include_router(_journal_router)
router.include_router(_activity_router)

__all__ = ["router"]
