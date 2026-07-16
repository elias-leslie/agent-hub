"""Helper utilities for the persona API."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.persona import Persona
from app.services._persona_crud import get_persona_limit
from app.services.persona_documents import (
    normalize_user_profile,
)
from app.services.persona_instruction_service import get_persona_heartbeat_instructions

from .schemas import PersonaResponse


async def persona_to_response(
    db: AsyncSession,
    persona: Persona,
    agent_slug: str = "persona",
) -> PersonaResponse:
    """Convert the already-loaded canonical Persona row to the response schema."""
    personality = (persona.personality or "").strip() or None
    heartbeat_instructions = await get_persona_heartbeat_instructions(db)
    user_context = (persona.user_context or "").strip() or None
    limits = None
    if persona.limits is not None:
        limits = {"max_turns": get_persona_limit(persona, "max_turns")}
    return PersonaResponse(
        id=persona.id,
        name=persona.name,
        personality=personality,
        user_profile=normalize_user_profile(persona.user_profile),
        heartbeat_instructions=heartbeat_instructions,
        user_context=user_context,
        voice_id=persona.voice_id,
        voice_enabled=persona.voice_enabled,
        heartbeat_interval_minutes=persona.heartbeat_interval_minutes,
        execution_state=persona.execution_state,
        avatar_url=persona.avatar_url,
        greeting=persona.greeting,
        onboarding_complete=persona.onboarding_complete,
        onboarding_phase=persona.onboarding_phase,
        session_reset_mode=persona.session_reset_mode,
        session_reset_hour=persona.session_reset_hour,
        session_reset_idle_minutes=persona.session_reset_idle_minutes,
        limits=limits,
        agent_slug=agent_slug,
        version=persona.version,
        updated_at=persona.updated_at.isoformat() if persona.updated_at else None,
    )

async def commit_and_refresh(db: AsyncSession, persona: Persona) -> Persona:
    """Commit the current transaction and refresh *persona* from the DB."""
    await db.commit()
    await db.refresh(persona)
    return persona
