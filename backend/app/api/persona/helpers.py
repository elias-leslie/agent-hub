"""Helper utilities for the persona API."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.persona import Persona
from app.services.persona_instruction_service import get_persona_heartbeat_instructions

from .constants import SHRINKAGE_MIN_LEN, SHRINKAGE_RATIO
from .schemas import PersonaResponse


async def persona_to_response(
    db: AsyncSession,
    persona: Persona,
    agent_slug: str = "persona",
) -> PersonaResponse:
    """Convert a Persona ORM object to response schema."""
    heartbeat_instructions = await get_persona_heartbeat_instructions(db)
    return PersonaResponse(
        id=persona.id,
        name=persona.name,
        personality=persona.personality,
        heartbeat_instructions=heartbeat_instructions,
        user_context=persona.user_context,
        voice_id=persona.voice_id,
        voice_enabled=persona.voice_enabled,
        heartbeat_interval_minutes=persona.heartbeat_interval_minutes,
        avatar_url=persona.avatar_url,
        greeting=persona.greeting,
        onboarding_complete=persona.onboarding_complete,
        onboarding_phase=persona.onboarding_phase,
        session_reset_mode=persona.session_reset_mode,
        session_reset_hour=persona.session_reset_hour,
        session_reset_idle_minutes=persona.session_reset_idle_minutes,
        limits=persona.limits,
        agent_slug=agent_slug,
        version=persona.version,
        updated_at=persona.updated_at.isoformat() if persona.updated_at else None,
    )


def apply_shrinkage_protection(
    persona: Persona,
    field: str,
    new_text: str,
    update_data: dict,
) -> None:
    """Raise HTTPException if new text is suspiciously shorter than old.

    Also saves a backup of the old value if the model has a ``<field>_previous``
    attribute, then writes the stripped new value into *update_data*.
    """
    old_text = getattr(persona, field) or ""
    stripped = new_text.strip()
    old_len = len(old_text)
    new_len = len(stripped)

    if old_len > SHRINKAGE_MIN_LEN and new_len < (old_len * SHRINKAGE_RATIO):
        raise HTTPException(
            status_code=422,
            detail=(
                f"REJECTED: New {field} ({new_len} chars) is dramatically shorter "
                f"than existing ({old_len} chars). This looks like accidental data loss."
            ),
        )

    backup_field = f"{field}_previous"
    if hasattr(persona, backup_field):
        setattr(persona, backup_field, old_text)

    update_data[field] = stripped


async def commit_and_refresh(db: AsyncSession, persona: Persona) -> Persona:
    """Commit the current transaction and refresh *persona* from the DB."""
    await db.commit()
    await db.refresh(persona)
    return persona
