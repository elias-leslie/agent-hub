"""Persona-related tool implementations for DirectToolExecutor.

Handles personality, user context, memory tagging, and onboarding.
"""

from __future__ import annotations

import inspect
import logging

logger = logging.getLogger(__name__)


async def read_personality() -> str:
    """Read the persona's current personality document."""
    try:
        from app.db import async_session
        from app.services.persona_service import get_or_create_persona

        async with async_session() as db:
            persona = await get_or_create_persona(db)
            if persona.personality:
                return persona.personality
            return "(No personality document set. Use write_personality to create one.)"
    except Exception as e:
        logger.exception("read_personality failed")
        return f"Error reading personality: {e}"


async def write_personality(personality: str, reason: str) -> str:
    """Update the persona's personality document with shrinkage protection."""
    if not personality or not personality.strip():
        return "Error: personality cannot be empty. Call read_personality first."

    try:
        from app.db import async_session
        from app.services.persona_documents import (
            PersonaDocumentShrinkageError,
            apply_persona_text_update,
        )
        from app.services.persona_service import get_or_create_persona

        async with async_session() as db:
            persona = await get_or_create_persona(db)
            try:
                old_len, new_len = apply_persona_text_update(
                    persona,
                    "personality",
                    personality,
                )
            except PersonaDocumentShrinkageError as exc:
                return (
                    f"{exc} Call read_personality first, then include ALL existing sections in your update. "
                    "If you genuinely need to shorten it, explain why in the reason."
                )
            persona.version += 1
            await db.commit()

        logger.info("personality updated: %d → %d chars", old_len, new_len)
        return f"Personality updated ({old_len} → {new_len} chars, version {persona.version}). Reason: {reason}"
    except Exception as e:
        logger.exception("write_personality failed")
        return f"Error writing personality: {e}"


async def write_user_context(user_context: str) -> str:
    """Update the persona's user context document with shrinkage protection."""
    if not user_context or not user_context.strip():
        return "Error: user_context cannot be empty. Call read_user_context first."

    try:
        from app.db import async_session
        from app.services.persona_documents import (
            PersonaDocumentShrinkageError,
            apply_persona_text_update,
        )
        from app.services.persona_service import get_or_create_persona

        async with async_session() as db:
            persona = await get_or_create_persona(db)
            try:
                old_len, new_len = apply_persona_text_update(
                    persona,
                    "user_context",
                    user_context,
                )
            except PersonaDocumentShrinkageError as exc:
                return (
                    f"{exc} Call read_user_context first, then include ALL existing sections in your update. "
                    "If you genuinely need to shorten it, explain why in the content."
                )
            persona.version += 1
            await db.commit()

        logger.info("user_context updated: %d → %d chars", old_len, new_len)
        return f"User context updated ({old_len} → {new_len} chars)"
    except Exception as e:
        logger.exception("write_user_context failed")
        return f"Error writing user context: {e}"


async def read_user_context() -> str:
    """Read the persona's current user context."""
    try:
        from app.db import async_session
        from app.services.persona_service import get_or_create_persona

        async with async_session() as db:
            persona = await get_or_create_persona(db)
            if persona.user_context:
                return persona.user_context
            return "(No user context set. Use write_user_context to record what you learn about the user.)"
    except Exception as e:
        logger.exception("read_user_context failed")
        return f"Error reading user context: {e}"


async def read_heartbeat_instructions() -> str:
    """Read the persona's current heartbeat instructions."""
    try:
        from app.db import async_session
        from app.services.persona_instruction_service import (
            get_persona_heartbeat_instructions,
        )

        async with async_session() as db:
            heartbeat_instructions = await get_persona_heartbeat_instructions(db)
            if heartbeat_instructions:
                return heartbeat_instructions
            return "(No heartbeat instructions set. Use write_heartbeat_instructions to create them.)"
    except Exception as e:
        logger.exception("read_heartbeat_instructions failed")
        return f"Error reading heartbeat instructions: {e}"


async def write_heartbeat_instructions(heartbeat_instructions: str, reason: str) -> str:
    """Update the persona's heartbeat instructions with shrinkage protection and supervisor review."""
    if not heartbeat_instructions or not heartbeat_instructions.strip():
        return "Error: heartbeat_instructions cannot be empty. Call read_heartbeat_instructions first."

    try:
        from app.db import async_session
        from app.services.persona_documents import (
            PersonaDocumentShrinkageError,
            validate_text_document_update,
        )
        from app.services.persona_instruction_service import (
            get_persona_heartbeat_instructions,
            set_persona_heartbeat_instructions,
        )
        from app.services.persona_service import get_or_create_persona
        from app.workflows._instruction_review import review_instruction_edit

        async with async_session() as db:
            persona = await get_or_create_persona(db)
            old_text = await get_persona_heartbeat_instructions(db)
            while inspect.isawaitable(old_text):
                old_text = await old_text
            if not isinstance(old_text, str):
                old_text = ""
            try:
                old_value, new_value = validate_text_document_update(
                    old_text,
                    heartbeat_instructions,
                    field_label="heartbeat_instructions",
                )
            except PersonaDocumentShrinkageError as exc:
                return (
                    f"{exc} Call read_heartbeat_instructions first, then include ALL existing sections. "
                    "If you genuinely need to shorten it, explain why in the reason."
                )

            # Supervisor review gate: check semantic safety before applying
            review = await review_instruction_edit(
                old_instructions=old_value,
                new_instructions=new_value,
                change_reason=reason,
            )
            if review.used and review.decision == "reject":
                logger.warning(
                    "Instruction edit rejected by supervisor: %s", review.reason,
                )
                return (
                    f"Edit REJECTED by supervisor review: {review.reason}\n\n"
                    "Revise your proposed changes to address the concern, then try again."
                )
            if review.used and review.decision == "revise":
                logger.info(
                    "Instruction edit needs revision per supervisor: %s", review.reason,
                )
                return (
                    f"Edit needs REVISION per supervisor review: {review.reason}\n\n"
                    "Adjust your proposed changes to address the feedback, then resubmit."
                )
            if review.used:
                logger.info("Instruction edit approved by supervisor")
            else:
                logger.warning("Instruction review unavailable — proceeding with write")

            old_len = len(old_value)
            new_len = len(new_value)

            await set_persona_heartbeat_instructions(db, heartbeat_instructions)
            persona.version += 1
            await db.commit()

        logger.info("heartbeat_instructions updated: %d → %d chars", old_len, new_len)
        reviewed = " (supervisor-approved)" if review.used else ""
        return f"Heartbeat instructions updated ({old_len} → {new_len} chars){reviewed}. Reason: {reason}"
    except Exception as e:
        logger.exception("write_heartbeat_instructions failed")
        return f"Error writing heartbeat instructions: {e}"


async def mark_memory_relevant(memory_uuid: str) -> str:
    """Add 'persona-relevant' tag to a memory episode."""
    try:
        from app.services.memory.episode_property_queries import get_episode_tags
        from app.services.memory.episode_property_setters import set_episode_tags
        from app.services.memory.memory_utils import resolve_uuid_prefix

        memory_uuid = await resolve_uuid_prefix(memory_uuid)
        current_tags = await get_episode_tags(memory_uuid)
        tag = "persona-relevant"
        if tag in current_tags:
            return f"Memory {memory_uuid[:8]} already tagged as persona-relevant"

        current_tags.append(tag)
        success = await set_episode_tags(memory_uuid, current_tags)
        if success:
            return f"Memory {memory_uuid[:8]} marked as persona-relevant"
        return f"Failed to tag memory {memory_uuid[:8]}"
    except Exception as e:
        logger.exception("mark_memory_relevant failed")
        return f"Error marking memory relevant: {e}"


async def mark_memory_irrelevant(memory_uuid: str) -> str:
    """Remove 'persona-relevant' tag from a memory episode."""
    try:
        from app.services.memory.episode_property_queries import get_episode_tags
        from app.services.memory.episode_property_setters import set_episode_tags
        from app.services.memory.memory_utils import resolve_uuid_prefix

        memory_uuid = await resolve_uuid_prefix(memory_uuid)
        current_tags = await get_episode_tags(memory_uuid)
        tag = "persona-relevant"
        if tag not in current_tags:
            return f"Memory {memory_uuid[:8]} is not tagged as persona-relevant"

        current_tags.remove(tag)
        success = await set_episode_tags(memory_uuid, current_tags)
        if success:
            return f"Removed persona-relevant tag from memory {memory_uuid[:8]}"
        return f"Failed to update tags for memory {memory_uuid[:8]}"
    except Exception as e:
        logger.exception("mark_memory_irrelevant failed")
        return f"Error marking memory irrelevant: {e}"


async def submit_onboarding(summary: str) -> str:
    """Submit the onboarding profile for dual-model approval."""
    try:
        from app.db import async_session
        from app.services.persona_service import (
            get_or_create_persona,
            submit_and_review_onboarding,
        )

        async with async_session() as db:
            persona = await get_or_create_persona(db)
            user_context_snapshot = persona.user_context

            result = await submit_and_review_onboarding(
                db, summary, user_context_snapshot,
            )

        if result["status"] == "approved":
            return (
                "Onboarding APPROVED by both reviewers. You're fully operational now.\n\n"
                f"Reviewer feedback:\n{result['feedback']}"
            )
        if result["status"] == "error":
            return (
                "Onboarding review FAILED due to system errors (reviewer models unreachable). "
                "This is NOT a content rejection — retry later.\n\n"
                f"Error details:\n{result['feedback']}"
            )
        return (
            "Onboarding REJECTED — needs revision. Review the feedback below and "
            "follow up with the user on the gaps.\n\n"
            f"Reviewer feedback:\n{result['feedback']}"
        )
    except Exception as e:
        logger.exception("submit_onboarding failed")
        return f"Error submitting onboarding: {e}"
