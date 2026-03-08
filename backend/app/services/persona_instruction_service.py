"""Prompt-backed storage for persona instruction documents."""

from __future__ import annotations

import inspect

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prompt import Prompt
from app.services.prompt_catalog import PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_SLUG
from app.services.prompt_service import get_prompt_by_slug


async def get_persona_heartbeat_instructions(db: AsyncSession) -> str | None:
    """Return the canonical prompt-backed heartbeat instructions for Jenny."""
    if db is None or not hasattr(db, "execute"):
        return None
    raw_prompt = await get_prompt_by_slug(db, PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_SLUG)
    while inspect.isawaitable(raw_prompt):
        raw_prompt = await raw_prompt
    prompt = raw_prompt if isinstance(raw_prompt, Prompt) else None
    if not prompt or not prompt.enabled:
        return None
    content = prompt.content.strip()
    return content or None


async def set_persona_heartbeat_instructions(
    db: AsyncSession,
    heartbeat_instructions: str,
) -> tuple[int, int]:
    """Upsert the canonical heartbeat-instructions prompt and return old/new lengths."""
    raw_prompt = await get_prompt_by_slug(db, PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_SLUG)
    while inspect.isawaitable(raw_prompt):
        raw_prompt = await raw_prompt
    prompt = raw_prompt if isinstance(raw_prompt, Prompt) else None
    old_content = prompt.content if prompt else None
    while inspect.isawaitable(old_content):
        old_content = await old_content
    if not isinstance(old_content, str):
        old_content = ""
    old_text = old_content.strip()
    new_text = heartbeat_instructions.strip()

    if prompt:
        prompt.name = "Persona Heartbeat Instructions"
        prompt.description = "Jenny-specific mutable guidance for heartbeat runs."
        prompt.content = new_text
        prompt.is_global = False
        prompt.enabled = True
    else:
        db.add(
            Prompt(
                slug=PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_SLUG,
                name="Persona Heartbeat Instructions",
                description="Jenny-specific mutable guidance for heartbeat runs.",
                content=new_text,
                is_global=False,
                enabled=True,
                exclude_agents=[],
            )
        )

    return len(old_text), len(new_text)
