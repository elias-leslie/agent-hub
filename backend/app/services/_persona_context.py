"""Persona context-building helpers — prompt injection for agents."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.persona import Persona
from app.services._persona_crud import get_persona_for_agent
from app.services._persona_templates import (
    EVOLUTION_TRIGGERS,
    ONBOARDING_PENDING_APPROVAL,
    build_onboarding_bootstrap,
    build_onboarding_continuation,
)

logger = logging.getLogger(__name__)


def _build_onboarding_section(persona: Persona) -> str | None:
    """Return the onboarding XML section for the current phase, or None."""
    phase = persona.onboarding_phase
    if phase == "not_started":
        text = build_onboarding_bootstrap(
            persona.name, has_prior_context=persona.user_context is not None
        )
        return f"<onboarding>\n{text}\n</onboarding>"
    if phase == "in_progress":
        if persona.user_context:
            text = build_onboarding_continuation(persona.name)
        else:
            text = build_onboarding_bootstrap(persona.name, has_prior_context=False)
        return f"<onboarding>\n{text}\n</onboarding>"
    if phase == "pending_approval":
        return f"<onboarding>\n{ONBOARDING_PENDING_APPROVAL}\n</onboarding>"
    return None  # phase == "complete"


def _format_journal_section(journal_memories: list) -> str:
    """Render a list of memory objects into a <recent_journal> XML block."""
    lines: list[str] = []
    for mem in journal_memories:
        entry_type = (mem.metadata_ or {}).get("entry_type", "observation")
        entry_date = (mem.valid_at or mem.created_at).strftime("%Y-%m-%d")
        lines.append(f"### {entry_date} [{entry_type}]")
        lines.append(mem.content)
        lines.append("")
    body = "".join(line + "\n" for line in lines).rstrip()
    return f"<recent_journal>\n{body}\n</recent_journal>"


_JOURNAL_LIMIT = 10
_JOURNAL_CHAR_BUDGET = 8_000


async def _fetch_journal_memories(persona: Persona, journal_days: int) -> list:
    """Fetch recent journal memories for the persona, budget-capped.

    Returns the most recent entries that fit within _JOURNAL_CHAR_BUDGET,
    up to _JOURNAL_LIMIT entries.  Oldest entries are dropped first.
    """
    from app.services.memory.repository import get_memory_repository

    repo = get_memory_repository()
    since_dt = datetime.now(UTC) - timedelta(days=journal_days)
    memories = await repo.list_by_scope_and_tier(
        scope="agent:persona",
        memory_type="journal",
        status="active",
        since=since_dt,
        order_by="created_at",
        limit=_JOURNAL_LIMIT,
    )
    # Enforce character budget — keep newest, drop oldest
    total = 0
    kept: list = []
    for mem in reversed(memories):
        total += len(mem.content)
        if total > _JOURNAL_CHAR_BUDGET:
            break
        kept.append(mem)
    kept.reverse()
    return kept


async def _handle_onboarding_phase_transition(
    db: AsyncSession, persona: Persona, phase: str
) -> None:
    """Advance onboarding phase from not_started to in_progress."""
    if phase == "not_started":
        persona.onboarding_phase = "in_progress"
        await db.flush()
        logger.info("Persona onboarding bootstrap injected; phase → in_progress")
    elif phase == "in_progress" and not persona.user_context:
        logger.info("Persona onboarding re-bootstrapped (no prior context)")


def _build_persona_sections(
    persona: Persona, *, task_type: str | None = None
) -> list[str]:
    """Assemble the static (non-journal) persona XML sections."""
    sections: list[str] = [f'<identity name="{persona.name}" />']
    if persona.greeting:
        sections.append(f"<greeting>\n{persona.greeting}\n</greeting>")
    if persona.personality:
        sections.append(f"<personality>\n{persona.personality}\n</personality>")
    if persona.heartbeat_instructions and task_type == "heartbeat":
        sections.append(
            f"<heartbeat_instructions>\n{persona.heartbeat_instructions}\n</heartbeat_instructions>"
        )
    if persona.user_context:
        sections.append(f"<user_context>\n{persona.user_context}\n</user_context>")
    return sections


async def get_persona_context_for_agent(
    db: AsyncSession,
    agent_id: int,
    journal_days: int = 7,
    task_type: str | None = None,
) -> str | None:
    """Build the full persona context block for prompt injection.

    Returns the formatted context string, or None if no persona exists.

    Args:
        task_type: When "heartbeat", includes heartbeat_instructions section.
            Other values (or None) omit it to save tokens in chat sessions.
    """
    persona = await get_persona_for_agent(db, agent_id)
    if not persona:
        return None

    sections: list[str] = []
    phase = persona.onboarding_phase

    onboarding_section = _build_onboarding_section(persona)
    if onboarding_section:
        sections.append(onboarding_section)
        await _handle_onboarding_phase_transition(db, persona, phase)

    sections.extend(_build_persona_sections(persona, task_type=task_type))

    journal_memories = await _fetch_journal_memories(persona, journal_days)
    if journal_memories:
        sections.append(_format_journal_section(journal_memories))

    if phase == "complete":
        sections.append(f"<evolution_guidelines>\n{EVOLUTION_TRIGGERS}\n</evolution_guidelines>")

    return "\n\n".join(sections)
