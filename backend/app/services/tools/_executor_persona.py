"""Persona-related tool implementations for DirectToolExecutor.

Handles personality, user context, memory tagging, and onboarding.
"""

from __future__ import annotations

import inspect
import logging

logger = logging.getLogger(__name__)


def _normalize_tags(tags: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for tag in tags or []:
        cleaned = tag.strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def _format_tags(tags: list[str]) -> str:
    return ", ".join(tags) if tags else "(none)"


async def _load_memory_tags(memory_uuid: str) -> tuple[str, list[str]]:
    from app.services.memory.episode_property_queries import get_episode_tags
    from app.services.memory.memory_utils import resolve_uuid_prefix

    resolved_uuid = await resolve_uuid_prefix(memory_uuid)
    current_tags = _normalize_tags(await get_episode_tags(resolved_uuid))
    return resolved_uuid, current_tags


async def _persist_memory_tags(memory_uuid: str, tags: list[str]) -> bool:
    from app.services.memory.episode_property_setters import set_episode_tags

    return await set_episode_tags(memory_uuid, tags)


def _apply_tag_action(
    action: str, current_tags: list[str], new_tags: list[str]
) -> list[str]:
    updated = list(current_tags)
    if action == "add_tags":
        for tag in new_tags:
            if tag not in updated:
                updated.append(tag)
    else:
        remove_set = set(new_tags)
        updated = [tag for tag in updated if tag not in remove_set]
    return updated


async def manage_memory_tags(
    action: str,
    memory_uuid: str | None,
    tags: list[str] | None,
) -> str:
    """Inspect or mutate tags on a memory episode."""
    if not memory_uuid:
        return "Error: memory_uuid required for manage_memory_tags"

    normalized_tags = _normalize_tags(tags)

    try:
        resolved_uuid, current_tags = await _load_memory_tags(memory_uuid)
        short_id = resolved_uuid[:8]

        if action == "get_tags":
            return f"Memory {short_id} tags: {_format_tags(current_tags)}"

        if action not in {"add_tags", "remove_tags"}:
            return (
                f"Error: Unknown action '{action}'. "
                "Use get_tags/add_tags/remove_tags."
            )

        if not normalized_tags:
            return f"Error: tags required for {action}"

        updated_tags = _apply_tag_action(action, current_tags, normalized_tags)

        if updated_tags == current_tags:
            return f"Memory {short_id} tags unchanged: {_format_tags(current_tags)}"

        success = await _persist_memory_tags(resolved_uuid, updated_tags)
        if success:
            return f"Updated tags for memory {short_id}: {_format_tags(updated_tags)}"
        return f"Failed to update tags for memory {short_id}"
    except Exception as e:
        logger.exception("manage_memory_tags failed")
        return f"Error managing memory tags: {e}"


async def read_personality() -> str:
    """Read the persona's current personality document."""
    try:
        from app.db import async_session
        from app.services.persona_document_prompt_service import (
            get_persona_personality_document,
        )

        async with async_session() as db:
            personality = await get_persona_personality_document(db)
            if personality:
                return personality
            return "(No personality document set. Use write_personality to create one.)"
    except Exception as e:
        logger.exception("read_personality failed")
        return f"Error reading personality: {e}"


async def _set_personality_guarded(db, personality: str, reason: str) -> tuple[int, int] | str:
    """Call set_persona_personality_document; return (old_len, new_len) or an error string."""
    from app.services.persona_document_prompt_service import set_persona_personality_document
    from app.services.persona_documents import PersonaDocumentShrinkageError

    try:
        return await set_persona_personality_document(
            db, personality,
            changed_by="persona_tool",
            change_reason=reason or "Persona personality tool update",
        )
    except PersonaDocumentShrinkageError as exc:
        return (
            f"{exc} Call read_personality first, then include ALL existing sections in your update. "
            "If you genuinely need to shorten it, explain why in the reason."
        )


async def write_personality(personality: str, reason: str) -> str:
    """Update the persona's personality document with shrinkage protection."""
    if not personality or not personality.strip():
        return "Error: personality cannot be empty. Call read_personality first."

    try:
        from app.db import async_session
        from app.services.persona_service import get_or_create_persona

        async with async_session() as db:
            persona = await get_or_create_persona(db)
            result = await _set_personality_guarded(db, personality, reason)
            if isinstance(result, str):
                return result
            old_len, new_len = result
            persona.version += 1
            await db.commit()

        logger.info("personality updated: %d → %d chars", old_len, new_len)
        return f"Personality updated ({old_len} → {new_len} chars, version {persona.version}). Reason: {reason}"
    except Exception as e:
        logger.exception("write_personality failed")
        return f"Error writing personality: {e}"


async def read_user_context() -> str:
    """Read the persona's current user context."""
    try:
        from app.db import async_session
        from app.services.persona_document_prompt_service import (
            get_persona_user_context_document,
        )

        async with async_session() as db:
            user_context = await get_persona_user_context_document(db)
            if user_context:
                return user_context
            return "(No user context set. Use write_user_context to record what you learn about the user.)"
    except Exception as e:
        logger.exception("read_user_context failed")
        return f"Error reading user context: {e}"


async def _set_user_context_guarded(db, user_context: str) -> tuple[int, int] | str:
    """Call set_persona_user_context_document; return (old_len, new_len) or an error string."""
    from app.services.persona_document_prompt_service import set_persona_user_context_document
    from app.services.persona_documents import PersonaDocumentShrinkageError

    try:
        return await set_persona_user_context_document(
            db, user_context,
            changed_by="persona_tool",
            change_reason="Persona user context tool update",
        )
    except PersonaDocumentShrinkageError as exc:
        return (
            f"{exc} Call read_user_context first, then include ALL existing sections in your update. "
            "If you genuinely need to shorten it, explain why in the content."
        )


async def write_user_context(user_context: str) -> str:
    """Update the persona's user context document with shrinkage protection."""
    if not user_context or not user_context.strip():
        return "Error: user_context cannot be empty. Call read_user_context first."

    try:
        from app.db import async_session
        from app.services.persona_service import get_or_create_persona

        async with async_session() as db:
            persona = await get_or_create_persona(db)
            result = await _set_user_context_guarded(db, user_context)
            if isinstance(result, str):
                return result
            old_len, new_len = result
            persona.version += 1
            await db.commit()

        logger.info("user_context updated: %d → %d chars", old_len, new_len)
        return f"User context updated ({old_len} → {new_len} chars)"
    except Exception as e:
        logger.exception("write_user_context failed")
        return f"Error writing user context: {e}"


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


async def _resolve_heartbeat_old_text(db) -> str:
    """Fetch and normalise the current heartbeat instructions string."""
    from app.services.persona_instruction_service import get_persona_heartbeat_instructions

    old_text = await get_persona_heartbeat_instructions(db)
    while inspect.isawaitable(old_text):
        old_text = await old_text
    return old_text if isinstance(old_text, str) else ""


async def _check_supervisor_review(
    old_value: str, new_value: str, reason: str
) -> tuple[str | None, bool]:
    """Run supervisor review.

    Returns (error_message, was_approved): error_message is set when the edit
    should be blocked; was_approved is True when the review ran and approved.
    """
    from app.workflows._instruction_review import review_instruction_edit

    review = await review_instruction_edit(
        old_instructions=old_value,
        new_instructions=new_value,
        change_reason=reason,
    )
    if review.used and review.decision == "reject":
        logger.warning("Instruction edit rejected by supervisor: %s", review.reason)
        return (
            f"Edit REJECTED by supervisor review: {review.reason}\n\n"
            "Revise your proposed changes to address the concern, then try again.",
            False,
        )
    if review.used and review.decision == "revise":
        logger.info("Instruction edit needs revision per supervisor: %s", review.reason)
        return (
            f"Edit needs REVISION per supervisor review: {review.reason}\n\n"
            "Adjust your proposed changes to address the feedback, then resubmit.",
            False,
        )
    if review.used:
        logger.info("Instruction edit approved by supervisor")
    else:
        logger.warning("Instruction review unavailable — proceeding with write")
    return None, review.used


def _validate_heartbeat_update(old_text: str, new_text: str) -> tuple[str, str] | str:
    """Validate the heartbeat text update; return (old_value, new_value) or an error string."""
    from app.services.persona_documents import (
        PersonaDocumentShrinkageError,
        validate_text_document_update,
    )

    try:
        return validate_text_document_update(
            old_text, new_text, field_label="heartbeat_instructions"
        )
    except PersonaDocumentShrinkageError as exc:
        return (
            f"{exc} Call read_heartbeat_instructions first, then include ALL existing sections. "
            "If you genuinely need to shorten it, explain why in the reason."
        )


async def write_heartbeat_instructions(heartbeat_instructions: str, reason: str) -> str:
    """Update the persona's heartbeat instructions with shrinkage protection and supervisor review."""
    if not heartbeat_instructions or not heartbeat_instructions.strip():
        return "Error: heartbeat_instructions cannot be empty. Call read_heartbeat_instructions first."

    try:
        from app.db import async_session
        from app.services.persona_instruction_service import set_persona_heartbeat_instructions
        from app.services.persona_service import get_or_create_persona

        async with async_session() as db:
            persona = await get_or_create_persona(db)
            old_text = await _resolve_heartbeat_old_text(db)
            validated = _validate_heartbeat_update(old_text, heartbeat_instructions)
            if isinstance(validated, str):
                return validated
            old_value, new_value = validated

            review_error, was_approved = await _check_supervisor_review(old_value, new_value, reason)
            if review_error is not None:
                return review_error

            old_len, new_len = len(old_value), len(new_value)
            await set_persona_heartbeat_instructions(db, heartbeat_instructions)
            persona.version += 1
            await db.commit()

        logger.info("heartbeat_instructions updated: %d → %d chars", old_len, new_len)
        reviewed = " (supervisor-approved)" if was_approved else ""
        return f"Heartbeat instructions updated ({old_len} → {new_len} chars){reviewed}. Reason: {reason}"
    except Exception as e:
        logger.exception("write_heartbeat_instructions failed")
        return f"Error writing heartbeat instructions: {e}"


async def mark_memory_relevant(memory_uuid: str) -> str:
    """Add 'persona-relevant' tag to a memory episode."""
    try:
        memory_uuid, current_tags = await _load_memory_tags(memory_uuid)
        tag = "persona-relevant"
        if tag in current_tags:
            return f"Memory {memory_uuid[:8]} already tagged as persona-relevant"

        current_tags.append(tag)
        success = await _persist_memory_tags(memory_uuid, current_tags)
        if success:
            return f"Memory {memory_uuid[:8]} marked as persona-relevant"
        return f"Failed to tag memory {memory_uuid[:8]}"
    except Exception as e:
        logger.exception("mark_memory_relevant failed")
        return f"Error marking memory relevant: {e}"


async def mark_memory_irrelevant(memory_uuid: str) -> str:
    """Remove 'persona-relevant' tag from a memory episode."""
    try:
        memory_uuid, current_tags = await _load_memory_tags(memory_uuid)
        tag = "persona-relevant"
        if tag not in current_tags:
            return f"Memory {memory_uuid[:8]} is not tagged as persona-relevant"

        current_tags.remove(tag)
        success = await _persist_memory_tags(memory_uuid, current_tags)
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
        from app.services.persona_document_prompt_service import (
            get_persona_user_context_document,
        )
        from app.services.persona_service import submit_and_review_onboarding

        async with async_session() as db:
            user_context_snapshot = await get_persona_user_context_document(db)
            result = await submit_and_review_onboarding(db, summary, user_context_snapshot)

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
