"""Persona API — first-class identity management for the concierge persona."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.agent_service import get_agent_service
from app.services.persona_document_prompt_service import (
    clear_persona_user_context_document,
    migrate_legacy_user_context_to_profile,
    set_persona_personality_document,
    set_persona_user_context_document,
)
from app.services.persona_documents import normalize_user_profile
from app.services.persona_identity import PERSONA_SLUG, sync_persona_name_to_agent
from app.services.persona_improvement import (
    get_persona_improvement_dashboard,
    update_persona_self_honing_schedule,
)
from app.services.persona_instruction_service import set_persona_heartbeat_instructions
from app.services.persona_service import get_or_create_persona

from .activity import router as _activity_router
from .automations import router as _automations_router
from .helpers import commit_and_refresh, persona_to_response
from .schemas import (
    PersonaImprovementDashboardResponse,
    PersonaImprovementScheduleResponse,
    PersonaImprovementScheduleUpdate,
    PersonaPersonalityResponse,
    PersonaPersonalityUpdate,
    PersonaResponse,
    PersonaUpdate,
)
from .stream import router as _stream_router

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/persona", tags=["persona"])


@router.get("", response_model=PersonaResponse)
async def get_persona(db: AsyncSession = Depends(get_db)) -> PersonaResponse:
    """Get the full persona configuration."""
    persona = await get_or_create_persona(db)
    if await migrate_legacy_user_context_to_profile(
        db,
        persona,
        changed_by="api",
        change_reason="Normalize legacy persona user context into structured profile",
    ):
        persona.version += 1
        await commit_and_refresh(db, persona)
    return await persona_to_response(db, persona)


@router.put("", response_model=PersonaResponse)
async def update_persona(
    update: PersonaUpdate,
    db: AsyncSession = Depends(get_db),
) -> PersonaResponse:
    """Update persona fields (partial update — only provided fields are changed)."""
    persona = await get_or_create_persona(db)
    update_data = update.model_dump(exclude_unset=True)

    if not update_data:
        return await persona_to_response(db, persona)

    personality = update_data.pop("personality", None)
    heartbeat_instructions = update_data.pop("heartbeat_instructions", None)
    user_profile = update_data.pop("user_profile", None)
    user_context = update_data.pop("user_context", None)

    if personality is not None:
        await set_persona_personality_document(
            db,
            personality,
            changed_by="api",
            change_reason="Persona settings update",
        )

    if heartbeat_instructions is not None:
        old_text = (await persona_to_response(db, persona)).heartbeat_instructions or ""
        old_len = len(old_text)
        new_text = heartbeat_instructions.strip()
        new_len = len(new_text)
        if old_len > 200 and new_len < (old_len * 0.5):
            from fastapi import HTTPException

            raise HTTPException(
                status_code=422,
                detail=(
                    f"REJECTED: New heartbeat_instructions ({new_len} chars) is dramatically shorter "
                    f"than existing ({old_len} chars). This looks like accidental data loss."
                ),
            )
        await set_persona_heartbeat_instructions(db, new_text)

    if user_context is not None:
        await set_persona_user_context_document(
            db,
            user_context,
            changed_by="api",
            change_reason="Persona settings update",
        )

    if user_profile is not None:
        persona.user_profile = normalize_user_profile(user_profile)

    for field, value in update_data.items():
        setattr(persona, field, value)

    if "name" in update_data:
        await sync_persona_name_to_agent(db, persona)

    persona.version += 1
    await commit_and_refresh(db, persona)
    if "name" in update_data:
        await get_agent_service().invalidate_slug(PERSONA_SLUG)

    logger.info("Persona updated: fields=%s", list(update_data.keys()))
    return await persona_to_response(
        db,
        persona,
    )


@router.get("/improvement", response_model=PersonaImprovementDashboardResponse)
async def get_improvement_dashboard(
    db: AsyncSession = Depends(get_db),
    days: Annotated[int, Query(ge=1, le=365, description="Days to include in improvement history")] = 30,
    limit: Annotated[int, Query(ge=1, le=50, description="Maximum recent rows per section")] = 8,
) -> PersonaImprovementDashboardResponse:
    """Return the focused persona improvement dashboard payload."""
    return PersonaImprovementDashboardResponse(
        **await get_persona_improvement_dashboard(db, days=days, limit=limit)
    )


@router.put("/improvement/schedule", response_model=PersonaImprovementScheduleResponse)
async def update_improvement_schedule(
    update: PersonaImprovementScheduleUpdate,
    db: AsyncSession = Depends(get_db),
) -> PersonaImprovementScheduleResponse:
    """Enable or disable the persona's scheduled improvement loop and update its cadence."""
    from fastapi import HTTPException

    try:
        payload = await update_persona_self_honing_schedule(
            db,
            enabled=update.enabled,
            cadence_minutes=update.cadence_minutes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PersonaImprovementScheduleResponse(**payload)


@router.post("/reset-onboarding", response_model=PersonaResponse)
async def reset_onboarding(db: AsyncSession = Depends(get_db)) -> PersonaResponse:
    """Reset onboarding so bootstrap instructions are injected on next conversation.

    Clears prompt-backed user context and resets onboarding_attempts so the persona starts
    truly fresh, with no stale context that could make it act mid-onboarding.
    """
    persona = await get_or_create_persona(db)
    persona.onboarding_complete = False
    persona.onboarding_phase = "not_started"
    persona.onboarding_attempts = 0
    await clear_persona_user_context_document(
        db,
        changed_by="api",
        change_reason="Persona onboarding reset",
    )
    persona.version += 1
    await commit_and_refresh(db, persona)
    logger.info("Persona onboarding fully reset (phase → not_started, context cleared)")
    return await persona_to_response(db, persona)


@router.get("/personality", response_model=PersonaPersonalityResponse)
async def get_personality(db: AsyncSession = Depends(get_db)) -> PersonaPersonalityResponse:
    """Get just the personality document (for agent self-read)."""
    persona = await get_or_create_persona(db)
    personality = (await persona_to_response(db, persona)).personality
    return PersonaPersonalityResponse(
        personality=personality,
        version=persona.version,
    )


@router.put("/personality", response_model=PersonaPersonalityResponse)
async def update_personality(
    update: PersonaPersonalityUpdate,
    db: AsyncSession = Depends(get_db),
) -> PersonaPersonalityResponse:
    """Update the personality document (for agent self-modification)."""
    persona = await get_or_create_persona(db)
    await set_persona_personality_document(
        db,
        update.personality,
        changed_by="api",
        change_reason=update.reason or "Persona personality update",
    )

    persona.version += 1
    await commit_and_refresh(db, persona)

    reason_log = f" reason={update.reason}" if update.reason else ""
    logger.info("Personality updated: version=%d%s", persona.version, reason_log)
    return PersonaPersonalityResponse(
        personality=(await persona_to_response(db, persona)).personality,
        version=persona.version,
    )


router.include_router(_activity_router)
router.include_router(_automations_router)
router.include_router(_stream_router)

__all__ = ["router"]
