"""Persona service — public API and singleton creation helper.

Business logic is split across focused sub-modules:
  _persona_crud.py       — query helpers and session-reset logic
  _persona_context.py    — prompt-injection / context building
  _persona_onboarding.py — dual-model onboarding review
  _persona_templates.py  — fallback defaults and onboarding review runner

Everything importable from this module before refactoring remains
importable from this same path.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.persona import Persona
from app.services._persona_context import get_persona_context_for_agent
from app.services._persona_crud import (
    DEFAULT_LIMITS,
    get_persona,
    get_persona_for_agent,
    get_persona_limit,
    get_persona_personality_for_agent,
    should_reset_persona_session,
)
from app.services._persona_onboarding import submit_and_review_onboarding
from app.services._persona_templates import DEFAULT_PERSONA_PERSONALITY
from app.services.owned_prompt_service import sync_persona_instruction_prompts

__all__ = [
    "DEFAULT_LIMITS",
    "DEFAULT_PERSONA_PERSONALITY",
    "get_or_create_persona",
    "get_persona",
    "get_persona_context_for_agent",
    "get_persona_for_agent",
    "get_persona_limit",
    "get_persona_personality_for_agent",
    "should_reset_persona_session",
    "submit_and_review_onboarding",
]

logger = logging.getLogger(__name__)


async def get_or_create_persona(db: AsyncSession) -> Persona:
    """Get the singleton persona, creating a default if missing (first-run only)."""
    persona = await get_persona(db)
    if persona:
        return persona

    from app.services.agent_service import get_agent_service

    agent_service = get_agent_service()
    agent = await agent_service.get_by_slug(db, "persona")
    if not agent:
        raise RuntimeError("Persona agent not found in database — run seed_agents.py")

    persona = Persona(
        agent_id=agent.id,
        name=agent.name,
        personality=DEFAULT_PERSONA_PERSONALITY,
        voice_id="en-US-AriaNeural",
        voice_enabled=False,
        heartbeat_interval_minutes=60,
        execution_state="active",
    )
    db.add(persona)
    await db.flush()
    await sync_persona_instruction_prompts(
        db,
        agent=agent,
        heartbeat_instructions="",
        change_reason="Initial persona instruction prompt bootstrap",
    )
    await db.commit()
    await db.refresh(persona)
    logger.info("Created default persona for agent %s", agent.slug)
    return persona
