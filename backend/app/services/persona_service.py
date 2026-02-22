"""Persona service — singleton access and helpers for the persona entity."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.persona import Persona
from app.models.persona_journal import PersonaJournal

logger = logging.getLogger(__name__)


async def get_persona(db: AsyncSession) -> Persona | None:
    """Get the singleton persona row (there's only one)."""
    result = await db.execute(select(Persona).limit(1))
    return result.scalar_one_or_none()


async def get_persona_for_agent(db: AsyncSession, agent_id: int) -> Persona | None:
    """Get persona for a specific agent ID."""
    result = await db.execute(select(Persona).where(Persona.agent_id == agent_id))
    return result.scalar_one_or_none()


async def get_persona_personality_for_agent(db: AsyncSession, agent_id: int) -> str | None:
    """Get just the personality text for an agent's persona."""
    persona = await get_persona_for_agent(db, agent_id)
    return persona.personality if persona else None


_ONBOARDING_BOOTSTRAP = """\
## First Interaction Bootstrap

This is your first conversation. Take a moment to:
1. Introduce yourself by your name
2. Ask the user about their preferences (communication style, notification frequency, \
how hands-on vs hands-off they want you to be)
3. Record what you learn using write_user_context
4. Review your personality document with read_personality and consider if adjustments are needed
5. Write a journal entry about this first interaction

Be yourself — warm, direct, competent. Show the user who you are."""

_EVOLUTION_TRIGGERS = """\
## Self-Evolution Guidelines

You can modify your own personality, knowledge, and memory. Follow these rules:

**Personality** (write_personality): Update when you discover a fundamental operating \
principle or communication insight. Always tell the human when you update it. \
Changes should reflect genuine learning, not trivial adjustments.

**User Context** (write_user_context): Update when you learn something about the user — \
preferences, patterns, schedule, communication style, pet peeves. This is cumulative; \
update with the full document each time.

**Journal** (write_journal): Write observations, decisions, learnings, and user insights. \
Use entry types: observation (what you noticed), decision (choices you made and why), \
learning (new understanding), user_insight (something you learned about the user).

**Memory Curation** (mark_memory_relevant / mark_memory_irrelevant): Mark memories as \
relevant to refine your long-term knowledge base. Tag memories that contain operational \
patterns, user preferences, or system knowledge you should retain.

Do NOT modify your personality for trivial reasons. Journal entries are cheap; \
personality changes are significant."""


async def get_persona_context_for_agent(
    db: AsyncSession,
    agent_id: int,
    journal_days: int = 7,
) -> str | None:
    """Build the full persona context block for prompt injection.

    Assembles all persona documents (personality, heartbeat_instructions,
    user_context, tools_guidance) plus recent journal entries into a
    structured block for injection into the agent's system prompt.

    On first interaction (onboarding_complete=False), injects bootstrap
    instructions and marks onboarding complete for subsequent calls.

    Args:
        db: Database session
        agent_id: Agent ID to look up persona for
        journal_days: Number of days of journal entries to include

    Returns:
        Formatted persona context string, or None if no persona exists.
    """
    persona = await get_persona_for_agent(db, agent_id)
    if not persona:
        return None

    sections: list[str] = []

    # Onboarding bootstrap (first interaction only)
    if not persona.onboarding_complete:
        sections.append(f"<onboarding>\n{_ONBOARDING_BOOTSTRAP}\n</onboarding>")
        persona.onboarding_complete = True
        await db.commit()
        logger.info("Persona onboarding bootstrap injected; marked complete")

    if persona.personality:
        sections.append(f"<personality>\n{persona.personality}\n</personality>")

    if persona.heartbeat_instructions:
        sections.append(
            f"<heartbeat_instructions>\n{persona.heartbeat_instructions}\n</heartbeat_instructions>"
        )

    if persona.user_context:
        sections.append(f"<user_context>\n{persona.user_context}\n</user_context>")

    if persona.tools_guidance:
        sections.append(f"<tools_guidance>\n{persona.tools_guidance}\n</tools_guidance>")

    # Recent journal entries
    since = date.today() - timedelta(days=journal_days)
    result = await db.execute(
        select(PersonaJournal)
        .where(
            PersonaJournal.persona_id == persona.id,
            PersonaJournal.entry_date >= since,
        )
        .order_by(PersonaJournal.entry_date.desc(), PersonaJournal.created_at.desc())
    )
    entries = result.scalars().all()
    if entries:
        journal_lines = []
        for entry in entries:
            journal_lines.append(f"### {entry.entry_date} [{entry.entry_type}]")
            journal_lines.append(entry.content)
            journal_lines.append("")
        sections.append(f"<recent_journal>\n{''.join(line + chr(10) for line in journal_lines).rstrip()}\n</recent_journal>")

    # Evolution triggers (always present in full mode)
    sections.append(f"<evolution_guidelines>\n{_EVOLUTION_TRIGGERS}\n</evolution_guidelines>")

    return "\n\n".join(sections)


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
