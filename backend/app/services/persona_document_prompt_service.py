"""Persona-row storage for editable identity and user-state documents.

Reusable operational instructions remain DB prompts.  The ``persona`` row is
the canonical source for persona identity/state so editable documents do not
form a second prompt-owned authority path.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.persona import Persona
from app.services.persona_documents import (
    normalize_user_profile,
    split_legacy_user_context,
    validate_text_document_update,
)
from app.services.prompt_catalog import (
    PERSONA_CHAT_USAGE_CONTEXT_PROMPT_SLUG,
)
from app.services.prompt_service import get_prompt_by_slug


async def _get_persona(db: AsyncSession) -> Persona:
    result = await db.execute(select(Persona).limit(1))
    persona = result.scalar_one_or_none()
    if persona is None:
        raise RuntimeError("Persona agent not found")
    return persona


async def _get_prompt_text(db: AsyncSession, slug: str) -> str | None:
    prompt = await get_prompt_by_slug(db, slug)
    if not prompt or not prompt.enabled:
        return None
    content = prompt.content.strip()
    return content or None


async def get_persona_personality_document(db: AsyncSession) -> str | None:
    persona = await _get_persona(db)
    content = (persona.personality or "").strip()
    return content or None


async def get_persona_user_context_document(db: AsyncSession) -> str | None:
    persona = await _get_persona(db)
    content = (persona.user_context or "").strip()
    return content or None


async def get_persona_chat_usage_context(db: AsyncSession) -> str | None:
    return await _get_prompt_text(db, PERSONA_CHAT_USAGE_CONTEXT_PROMPT_SLUG)


async def set_persona_personality_document(
    db: AsyncSession,
    personality: str,
    *,
    changed_by: str | None = None,
    change_reason: str | None = None,
) -> tuple[int, int]:
    persona = await _get_persona(db)
    old_text = persona.personality or ""
    _old_value, new_value = validate_text_document_update(
        old_text,
        personality,
        field_label="personality",
    )
    if new_value != old_text:
        persona.personality_previous = old_text or None
        persona.personality = new_value
        await db.flush()
    return len(old_text), len(new_value)


async def set_persona_user_context_document(
    db: AsyncSession,
    user_context: str,
    *,
    changed_by: str | None = None,
    change_reason: str | None = None,
) -> tuple[int, int]:
    persona = await _get_persona(db)
    old_text = persona.user_context or ""
    _old_value, new_value = validate_text_document_update(
        old_text,
        user_context,
        field_label="user_context",
    )
    if new_value != old_text:
        persona.user_context_previous = old_text or None
        persona.user_context = new_value or None
        await db.flush()
    return len(old_text), len(new_value)


async def clear_persona_user_context_document(
    db: AsyncSession,
    *,
    changed_by: str | None = None,
    change_reason: str | None = None,
) -> None:
    persona = await _get_persona(db)
    old_text = persona.user_context or ""
    if old_text:
        persona.user_context_previous = old_text
        persona.user_context = None
        await db.flush()


async def migrate_legacy_user_context_to_profile(
    db: AsyncSession,
    persona: Persona,
    *,
    changed_by: str | None = None,
    change_reason: str | None = None,
) -> bool:
    """Move legacy structured user-context content into persona.user_profile."""
    existing_profile = normalize_user_profile(persona.user_profile) or {}
    user_context = persona.user_context
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
        persona.user_context_previous = normalized_context or None
        persona.user_context = normalized_remaining_notes or None
    if profile_changed or context_changed:
        await db.flush()
    return True


__all__ = [
    "clear_persona_user_context_document",
    "get_persona_personality_document",
    "get_persona_user_context_document",
    "migrate_legacy_user_context_to_profile",
    "set_persona_personality_document",
    "set_persona_user_context_document",
]
