"""Helpers for persona display-name resolution and sync."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.persona import Persona

PERSONA_SLUG = "persona"
DEFAULT_PERSONA_DISPLAY_NAME = "Persona"


async def get_persona_display_name(
    db: AsyncSession,
    *,
    fallback: str | None = None,
) -> str:
    """Return the current persona display name from the persona row when available."""
    result = await db.execute(select(Persona.name).limit(1))
    persona_name = result.scalar_one_or_none()
    if isinstance(persona_name, str) and persona_name.strip():
        return persona_name.strip()

    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()

    result = await db.execute(
        select(Agent.name).where(Agent.slug == PERSONA_SLUG).limit(1)
    )
    agent_name = result.scalar_one_or_none()
    if isinstance(agent_name, str) and agent_name.strip():
        return agent_name.strip()

    return DEFAULT_PERSONA_DISPLAY_NAME


async def sync_persona_name_to_agent(db: AsyncSession, persona: Persona) -> None:
    """Keep the backing agent row aligned with the persona display name."""
    display_name = persona.name.strip() or DEFAULT_PERSONA_DISPLAY_NAME
    result = await db.execute(select(Agent).where(Agent.id == persona.agent_id).limit(1))
    agent = result.scalar_one_or_none()
    if agent is not None and agent.name != display_name:
        agent.name = display_name
