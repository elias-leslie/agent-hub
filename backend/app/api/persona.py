"""Persona API — first-class identity management for the concierge persona."""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.persona import Persona
from app.services.persona_service import get_or_create_persona

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/persona", tags=["persona"])


# --- Schemas ---


class PersonaResponse(BaseModel):
    """Full persona representation."""

    id: int
    name: str
    personality: str | None = None
    heartbeat_instructions: str | None = None
    user_context: str | None = None
    voice_id: str = "en-US-AriaNeural"
    voice_enabled: bool = False
    heartbeat_interval_minutes: int = 60
    avatar_url: str | None = None
    greeting: str | None = None
    onboarding_complete: bool = False
    onboarding_phase: str = "not_started"
    session_reset_mode: str = "off"
    session_reset_hour: int = 9
    session_reset_idle_minutes: int = 120
    limits: dict | None = None
    agent_slug: str = "persona"
    version: int = 1
    updated_at: str | None = None


class PersonaUpdate(BaseModel):
    """Partial update for persona fields."""

    name: str | None = Field(default=None, max_length=100)
    personality: str | None = None
    heartbeat_instructions: str | None = None
    user_context: str | None = None
    voice_id: str | None = Field(default=None, max_length=200)
    voice_enabled: bool | None = None
    heartbeat_interval_minutes: int | None = Field(default=None, ge=0, le=1440)
    avatar_url: str | None = Field(default=None, max_length=500)
    greeting: str | None = None
    session_reset_mode: str | None = Field(default=None, pattern="^(off|daily|idle)$")
    session_reset_hour: int | None = Field(default=None, ge=0, le=23)
    session_reset_idle_minutes: int | None = Field(default=None, ge=5, le=1440)
    limits: dict | None = None


class PersonaPersonalityResponse(BaseModel):
    """Just the personality text."""

    personality: str | None = None
    version: int = 1


class PersonaPersonalityUpdate(BaseModel):
    """Update the personality document."""

    personality: str = Field(description="The new personality document (markdown)")
    reason: str = Field(
        default="",
        description="Why the personality is being updated (for audit trail)",
    )


# --- Helpers ---


def _persona_to_response(persona: Persona, agent_slug: str = "persona") -> PersonaResponse:
    """Convert a Persona ORM object to response schema."""
    return PersonaResponse(
        id=persona.id,
        name=persona.name,
        personality=persona.personality,
        heartbeat_instructions=persona.heartbeat_instructions,
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


# --- Endpoints ---


@router.get("", response_model=PersonaResponse)
async def get_persona(db: AsyncSession = Depends(get_db)) -> PersonaResponse:
    """Get the full persona configuration."""
    persona = await get_or_create_persona(db)
    return _persona_to_response(persona)


@router.put("", response_model=PersonaResponse)
async def update_persona(
    update: PersonaUpdate,
    db: AsyncSession = Depends(get_db),
) -> PersonaResponse:
    """Update persona fields (partial update — only provided fields are changed)."""
    persona = await get_or_create_persona(db)

    update_data = update.model_dump(exclude_unset=True)
    if not update_data:
        return _persona_to_response(persona)

    for field, value in update_data.items():
        setattr(persona, field, value)

    persona.version += 1
    await db.commit()
    await db.refresh(persona)

    logger.info("Persona updated: fields=%s", list(update_data.keys()))
    return _persona_to_response(persona)


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
    await db.commit()
    await db.refresh(persona)
    logger.info("Persona onboarding fully reset (phase → not_started, context cleared)")
    return _persona_to_response(persona)


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
    persona.personality = update.personality
    persona.version += 1
    await db.commit()
    await db.refresh(persona)

    reason_log = f" reason={update.reason}" if update.reason else ""
    logger.info("Personality updated: version=%d%s", persona.version, reason_log)
    return PersonaPersonalityResponse(
        personality=persona.personality,
        version=persona.version,
    )


# --- Journal Schemas ---


class JournalEntryResponse(BaseModel):
    """A single journal entry."""

    id: int
    entry_date: str
    content: str
    entry_type: str
    created_at: str | None = None


class JournalListResponse(BaseModel):
    """List of journal entries."""

    entries: list[JournalEntryResponse]
    total: int


# --- Journal Endpoints ---


@router.get("/journal", response_model=JournalListResponse)
async def get_journal(
    days_back: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> JournalListResponse:
    """Get recent journal entries (read-only for UI)."""
    from datetime import UTC, datetime

    from app.services.memory.repository import get_memory_repository

    repo = get_memory_repository()
    since_dt = datetime.now(UTC) - timedelta(days=days_back)
    memories = await repo.list_by_scope_and_tier(
        scope="agent:persona",
        memory_type="journal",
        status="active",
        since=since_dt,
        order_by="created_at",
    )

    return JournalListResponse(
        entries=[
            JournalEntryResponse(
                id=0,  # memories use UUID; id kept for schema compat
                entry_date=(m.valid_at or m.created_at).strftime("%Y-%m-%d"),
                content=m.content,
                entry_type=(m.metadata_ or {}).get("entry_type", "observation"),
                created_at=m.created_at.isoformat() if m.created_at else None,
            )
            for m in memories
        ],
        total=len(memories),
    )
