"""Persona-related tool implementations for DirectToolExecutor.

Handles personality, journal, user context, memory tagging, and onboarding.
"""

from __future__ import annotations

import logging
from datetime import UTC

logger = logging.getLogger(__name__)

VALID_ENTRY_TYPES: frozenset[str] = frozenset({"observation", "decision", "learning", "user_insight"})


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
    """Update the persona's personality document."""
    try:
        from app.db import async_session
        from app.services.persona_service import get_or_create_persona

        async with async_session() as db:
            persona = await get_or_create_persona(db)
            persona.personality = personality
            persona.version += 1
            await db.commit()

        return f"Personality updated (version {persona.version}). Reason: {reason}"
    except Exception as e:
        logger.exception("write_personality failed")
        return f"Error writing personality: {e}"


async def write_journal(content: str, entry_type: str = "observation") -> str:
    """Write a journal entry for today."""
    if entry_type not in VALID_ENTRY_TYPES:
        return (
            f"Invalid entry_type '{entry_type}'. "
            f"Must be one of: {', '.join(sorted(VALID_ENTRY_TYPES))}"
        )
    try:
        from datetime import datetime

        from app.services.memory.embedder import get_embedder
        from app.services.memory.repository import get_memory_repository

        repo = get_memory_repository()
        embedder = get_embedder()
        embedding = await embedder.embed(content)
        now = datetime.now(UTC)

        await repo.create(
            content=content,
            memory_type="journal",
            scope="agent:persona",
            source="agent:persona",
            source_description=f"Persona journal ({entry_type})",
            embedding=embedding,
            metadata_={"entry_type": entry_type},
            valid_at=now,
        )

        return f"Journal entry recorded ({entry_type})"
    except Exception as e:
        logger.exception("write_journal failed")
        return f"Error writing journal: {e}"


async def read_journal(days_back: int = 7) -> str:
    """Read recent journal entries."""
    try:
        from datetime import datetime, timedelta

        from app.services.memory.repository import get_memory_repository

        repo = get_memory_repository()
        since = datetime.now(UTC) - timedelta(days=days_back)
        memories = await repo.list_by_scope_and_tier(
            scope="agent:persona",
            memory_type="journal",
            status="active",
            since=since,
            order_by="created_at",
        )

        if not memories:
            return f"(No journal entries in the last {days_back} days)"

        lines = []
        for mem in memories:
            entry_type = (mem.metadata_ or {}).get("entry_type", "observation")
            entry_date = (mem.valid_at or mem.created_at).strftime("%Y-%m-%d")
            lines.append(f"## {entry_date} [{entry_type}]")
            lines.append(mem.content)
            lines.append("")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("read_journal failed")
        return f"Error reading journal: {e}"


async def search_journal(query: str, days_back: int = 30) -> str:
    """Search journal entries by content."""
    try:
        from datetime import datetime, timedelta

        from app.services.memory.repository import get_memory_repository

        repo = get_memory_repository()
        since = datetime.now(UTC) - timedelta(days=days_back)
        all_journal = await repo.list_by_scope_and_tier(
            scope="agent:persona",
            memory_type="journal",
            status="active",
            since=since,
            order_by="created_at",
            limit=200,
        )
        # Filter by content match in Python (journal volume is low)
        q_lower = query.lower()
        entries = [m for m in all_journal if q_lower in m.content.lower()]

        if not entries:
            return f"(No journal entries matching '{query}' in the last {days_back} days)"

        lines = []
        for mem in entries:
            entry_type = (mem.metadata_ or {}).get("entry_type", "observation")
            entry_date = (mem.valid_at or mem.created_at).strftime("%Y-%m-%d")
            lines.append(f"## {entry_date} [{entry_type}]")
            lines.append(mem.content)
            lines.append("")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("search_journal failed")
        return f"Error searching journal: {e}"


async def write_user_context(user_context: str) -> str:
    """Update the persona's user context document."""
    try:
        from app.db import async_session
        from app.services.persona_service import get_or_create_persona

        async with async_session() as db:
            persona = await get_or_create_persona(db)
            persona.user_context = user_context
            persona.version += 1
            await db.commit()

        return "User context updated"
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


async def mark_memory_relevant(memory_uuid: str) -> str:
    """Add 'persona-relevant' tag to a memory episode."""
    try:
        from app.services.memory.episode_property_queries import get_episode_tags
        from app.services.memory.episode_property_setters import set_episode_tags

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
