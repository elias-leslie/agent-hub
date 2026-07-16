"""Prompt-backed storage for persona instruction documents."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.services.owned_prompt_service import sync_persona_instruction_prompts
from app.services.prompt_catalog import (
    PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_SLUG,
)
from app.services.prompt_service import get_prompt_by_slug


async def _get_persona_agent(db: AsyncSession) -> Agent:
    result = await db.execute(select(Agent).where(Agent.slug == "persona"))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise RuntimeError("Persona agent not found")
    return agent


async def get_persona_heartbeat_instructions(db: AsyncSession) -> str | None:
    """Return the canonical prompt-backed heartbeat instructions for the persona."""
    if db is None or not hasattr(db, "execute"):
        return None
    prompt = await get_prompt_by_slug(db, PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_SLUG)
    if not prompt or not prompt.enabled:
        return None
    content = prompt.content.strip()
    return content or None


async def set_persona_heartbeat_instructions(
    db: AsyncSession,
    heartbeat_instructions: str,
    *,
    changed_by: str | None = None,
    change_reason: str | None = None,
) -> tuple[int, int]:
    """Upsert the canonical heartbeat-instructions prompt and return old/new lengths."""
    prompt = await get_prompt_by_slug(db, PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_SLUG)
    old_text = prompt.content.strip() if prompt else ""
    new_text = heartbeat_instructions.strip()
    agent = await _get_persona_agent(db)
    await sync_persona_instruction_prompts(
        db,
        agent=agent,
        heartbeat_instructions=new_text,
        changed_by=changed_by,
        change_reason=change_reason or "Persona heartbeat instructions updated",
    )
    return len(old_text), len(new_text)
