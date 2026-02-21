"""Persona API — first-class identity management for the concierge persona."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.persona_service import get_or_create_persona

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/persona", tags=["persona"])


# --- Schemas ---


class PersonaResponse(BaseModel):
    """Full persona representation."""

    id: int
    name: str
    soul: str | None = None
    voice_id: str = "en-US-AriaNeural"
    voice_enabled: bool = False
    heartbeat_interval_minutes: int = 60
    avatar_url: str | None = None
    greeting: str | None = None
    agent_slug: str = "persona"
    version: int = 1
    updated_at: str | None = None


class PersonaUpdate(BaseModel):
    """Partial update for persona fields."""

    name: str | None = Field(default=None, max_length=100)
    soul: str | None = None
    voice_id: str | None = Field(default=None, max_length=200)
    voice_enabled: bool | None = None
    heartbeat_interval_minutes: int | None = Field(default=None, ge=0, le=1440)
    avatar_url: str | None = Field(default=None, max_length=500)
    greeting: str | None = None


class PersonaSoulResponse(BaseModel):
    """Just the soul text."""

    soul: str | None = None
    version: int = 1


class PersonaSoulUpdate(BaseModel):
    """Update the soul document."""

    soul: str = Field(description="The new soul document (markdown)")
    reason: str = Field(
        default="",
        description="Why the soul is being updated (for audit trail)",
    )


# --- Helpers ---


def _persona_to_response(persona: object, agent_slug: str = "persona") -> PersonaResponse:
    """Convert a Persona ORM object to response schema."""
    return PersonaResponse(
        id=persona.id,  # type: ignore[attr-defined]
        name=persona.name,  # type: ignore[attr-defined]
        soul=persona.soul,  # type: ignore[attr-defined]
        voice_id=persona.voice_id,  # type: ignore[attr-defined]
        voice_enabled=persona.voice_enabled,  # type: ignore[attr-defined]
        heartbeat_interval_minutes=persona.heartbeat_interval_minutes,  # type: ignore[attr-defined]
        avatar_url=persona.avatar_url,  # type: ignore[attr-defined]
        greeting=persona.greeting,  # type: ignore[attr-defined]
        agent_slug=agent_slug,
        version=persona.version,  # type: ignore[attr-defined]
        updated_at=persona.updated_at.isoformat() if persona.updated_at else None,  # type: ignore[attr-defined]
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

    persona.version += 1  # type: ignore[attr-defined]
    await db.commit()
    await db.refresh(persona)

    logger.info("Persona updated: fields=%s", list(update_data.keys()))
    return _persona_to_response(persona)


@router.get("/soul", response_model=PersonaSoulResponse)
async def get_soul(db: AsyncSession = Depends(get_db)) -> PersonaSoulResponse:
    """Get just the soul document (for agent self-read)."""
    persona = await get_or_create_persona(db)
    return PersonaSoulResponse(
        soul=persona.soul,  # type: ignore[attr-defined]
        version=persona.version,  # type: ignore[attr-defined]
    )


@router.put("/soul", response_model=PersonaSoulResponse)
async def update_soul(
    update: PersonaSoulUpdate,
    db: AsyncSession = Depends(get_db),
) -> PersonaSoulResponse:
    """Update the soul document (for agent self-modification)."""
    persona = await get_or_create_persona(db)
    persona.soul = update.soul  # type: ignore[attr-defined]
    persona.version += 1  # type: ignore[attr-defined]
    await db.commit()
    await db.refresh(persona)

    reason_log = f" reason={update.reason}" if update.reason else ""
    logger.info("Soul updated: version=%d%s", persona.version, reason_log)  # type: ignore[attr-defined]
    return PersonaSoulResponse(
        soul=persona.soul,  # type: ignore[attr-defined]
        version=persona.version,  # type: ignore[attr-defined]
    )
