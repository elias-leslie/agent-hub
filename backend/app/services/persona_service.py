"""Persona service — singleton access and helpers for the persona entity."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.persona import Persona

logger = logging.getLogger(__name__)


async def get_persona(db: AsyncSession) -> Persona | None:
    """Get the singleton persona row (there's only one)."""
    result = await db.execute(select(Persona).limit(1))
    return result.scalar_one_or_none()


async def get_persona_for_agent(db: AsyncSession, agent_id: int) -> Persona | None:
    """Get persona for a specific agent ID."""
    result = await db.execute(select(Persona).where(Persona.agent_id == agent_id))
    return result.scalar_one_or_none()


async def get_persona_soul_for_agent(db: AsyncSession, agent_id: int) -> str | None:
    """Get just the soul text for an agent's persona."""
    persona = await get_persona_for_agent(db, agent_id)
    return persona.soul if persona else None


async def get_or_create_persona(db: AsyncSession) -> Persona:
    """Get the singleton persona, creating a default if missing.

    This should only create on first run / fresh DB — the migration
    seeds the initial row.
    """
    persona = await get_persona(db)
    if persona:
        return persona

    # Fallback: create default persona linked to the persona agent
    from app.services.agent_service import get_agent_service

    agent_service = get_agent_service()
    agent = await agent_service.get_by_slug(db, "persona")
    if not agent:
        raise RuntimeError("Persona agent not found in database — run seed_agents.py")

    persona = Persona(
        agent_id=agent.id,
        name=agent.name,
        voice_id="en-US-AriaNeural",
        voice_enabled=False,
        heartbeat_interval_minutes=60,
    )
    db.add(persona)
    await db.commit()
    await db.refresh(persona)
    logger.info("Created default persona for agent %s", agent.slug)
    return persona
