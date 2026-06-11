"""Prompt-backed storage for the persona's editable document prompts."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.persona import Persona
from app.services.owned_prompt_service import sync_persona_document_prompts
from app.services.persona_documents import (
    normalize_user_profile,
    split_legacy_user_context,
    validate_text_document_update,
)
from app.services.prompt_catalog import (
    PERSONA_CHAT_USAGE_CONTEXT_PROMPT_SLUG,
    PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_SLUG,
    PERSONA_PERSONALITY_PROMPT_SLUG,
    PERSONA_USER_CONTEXT_PROMPT_SLUG,
)
from app.services.prompt_service import get_prompt_by_slug


async def _get_persona_agent(db: AsyncSession) -> Agent:
    result = await db.execute(select(Agent).where(Agent.slug == "persona"))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise RuntimeError("Persona agent not found")
    return agent


async def _get_prompt_text(db: AsyncSession, slug: str) -> str | None:
    prompt = await get_prompt_by_slug(db, slug)
    if not prompt or not prompt.enabled:
        return None
    content = prompt.content.strip()
    return content or None


async def get_persona_personality_document(db: AsyncSession) -> str | None:
    return await _get_prompt_text(db, PERSONA_PERSONALITY_PROMPT_SLUG)


async def get_persona_user_context_document(db: AsyncSession) -> str | None:
    return await _get_prompt_text(db, PERSONA_USER_CONTEXT_PROMPT_SLUG)


async def get_persona_chat_usage_context(db: AsyncSession) -> str | None:
    return await _get_prompt_text(db, PERSONA_CHAT_USAGE_CONTEXT_PROMPT_SLUG)


async def set_persona_personality_document(
    db: AsyncSession,
    personality: str,
    *,
    changed_by: str | None = None,
    change_reason: str | None = None,
) -> tuple[int, int]:
    old_text = await get_persona_personality_document(db) or ""
    _old_value, new_value = validate_text_document_update(
        old_text,
        personality,
        field_label="personality",
    )
    agent = await _get_persona_agent(db)
    user_context = await get_persona_user_context_document(db) or ""
    heartbeat = await _get_prompt_text(db, PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_SLUG) or ""
    await sync_persona_document_prompts(
        db,
        agent=agent,
        personality=new_value,
        user_context=user_context,
        heartbeat_instructions=heartbeat,
        changed_by=changed_by,
        change_reason=change_reason or "Persona personality document updated",
    )
    return len(old_text), len(new_value)


async def set_persona_user_context_document(
    db: AsyncSession,
    user_context: str,
    *,
    changed_by: str | None = None,
    change_reason: str | None = None,
) -> tuple[int, int]:
    old_text = await get_persona_user_context_document(db) or ""
    _old_value, new_value = validate_text_document_update(
        old_text,
        user_context,
        field_label="user_context",
    )
    agent = await _get_persona_agent(db)
    personality = await get_persona_personality_document(db) or ""
    heartbeat = await _get_prompt_text(db, PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_SLUG) or ""
    await sync_persona_document_prompts(
        db,
        agent=agent,
        personality=personality,
        user_context=new_value,
        heartbeat_instructions=heartbeat,
        changed_by=changed_by,
        change_reason=change_reason or "Persona user context updated",
    )
    return len(old_text), len(new_value)


async def clear_persona_user_context_document(
    db: AsyncSession,
    *,
    changed_by: str | None = None,
    change_reason: str | None = None,
) -> None:
    agent = await _get_persona_agent(db)
    personality = await get_persona_personality_document(db) or ""
    heartbeat = await _get_prompt_text(db, PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_SLUG) or ""
    await sync_persona_document_prompts(
        db,
        agent=agent,
        personality=personality,
        user_context="",
        heartbeat_instructions=heartbeat,
        changed_by=changed_by,
        change_reason=change_reason or "Persona user context cleared",
    )


async def migrate_legacy_user_context_to_profile(
    db: AsyncSession,
    persona: Persona,
    *,
    changed_by: str | None = None,
    change_reason: str | None = None,
) -> bool:
    """Move legacy structured user-context content into persona.user_profile."""
    existing_profile = normalize_user_profile(persona.user_profile) or {}
    user_context = await get_persona_user_context_document(db)
    migrated_profile, remaining_notes = split_legacy_user_context(user_context)
    if not migrated_profile:
        return False

    merged_profile = normalize_user_profile({**migrated_profile, **existing_profile}) or None
    normalized_context = (user_context or "").strip()
    normalized_remaining_notes = (remaining_notes or "").strip()

    profile_changed = merged_profile != (existing_profile or None)
    context_changed = normalized_remaining_notes != normalized_context
    if not profile_changed and not context_changed:
        return False

    if profile_changed:
        persona.user_profile = merged_profile

    if context_changed:
        agent = await _get_persona_agent(db)
        personality = await get_persona_personality_document(db) or ""
        heartbeat = await _get_prompt_text(db, PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_SLUG) or ""
        await sync_persona_document_prompts(
            db,
            agent=agent,
            personality=personality,
            user_context=normalized_remaining_notes,
            heartbeat_instructions=heartbeat,
            changed_by=changed_by,
            change_reason=change_reason or "Persona user context normalized into structured profile",
        )
    return True


__all__ = [
    "clear_persona_user_context_document",
    "get_persona_personality_document",
    "get_persona_user_context_document",
    "migrate_legacy_user_context_to_profile",
    "set_persona_personality_document",
    "set_persona_user_context_document",
]
