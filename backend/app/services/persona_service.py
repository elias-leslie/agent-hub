"""Persona service — singleton access and helpers for the persona entity."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.persona import Persona
from app.services._persona_templates import (
    DEFAULT_PERSONA_PERSONALITY,
    EVOLUTION_TRIGGERS,
    ONBOARDING_PENDING_APPROVAL,
    build_onboarding_bootstrap,
    build_onboarding_continuation,
    build_review_prompt,
    run_single_review,
)

logger = logging.getLogger(__name__)

# Default limits — generous, adjustable via persona.limits JSON
DEFAULT_LIMITS: dict[str, int] = {
    "max_scheduled_jobs": 200,
    "max_job_turns": 15,
    "max_steers_per_consultation": 50,
    "max_concurrent_consultations": 20,
    "max_journal_entries": 50,
    "max_onboarding_attempts": 3,
}

# Re-export private template helpers so existing imports (e.g. tests) keep working
_build_onboarding_bootstrap = build_onboarding_bootstrap
_build_onboarding_continuation = build_onboarding_continuation
_ONBOARDING_PENDING_APPROVAL = ONBOARDING_PENDING_APPROVAL
_EVOLUTION_TRIGGERS = EVOLUTION_TRIGGERS


def get_persona_limit(persona: Persona | None, key: str) -> int:
    """Get a configurable limit, falling back to defaults."""
    if persona and persona.limits and key in persona.limits:
        return int(persona.limits[key])
    return DEFAULT_LIMITS.get(key, 0)


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


async def should_reset_persona_session(db: AsyncSession, session: object) -> bool:
    """Return True if the persona session should be closed and a new one created."""
    persona = await get_persona(db)
    if not persona or persona.session_reset_mode == "off":
        return False

    session_updated = getattr(session, "updated_at", None)
    if not session_updated:
        return False

    if session_updated.tzinfo is None:
        session_updated = session_updated.replace(tzinfo=UTC)

    now = datetime.now(UTC)

    if persona.session_reset_mode == "daily":
        reset_time = now.replace(
            hour=persona.session_reset_hour, minute=0, second=0, microsecond=0
        )
        if now < reset_time:
            reset_time -= timedelta(days=1)
        return session_updated < reset_time

    if persona.session_reset_mode == "idle":
        elapsed_minutes = (now - session_updated).total_seconds() / 60
        return elapsed_minutes >= persona.session_reset_idle_minutes

    return False


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


async def get_persona_context_for_agent(
    db: AsyncSession,
    agent_id: int,
    journal_days: int = 7,
) -> str | None:
    """Build the full persona context block for prompt injection.

    Assembles personality, heartbeat_instructions, user_context, and recent
    journal entries into a structured XML block. Onboarding injection is
    phase-based; phase not_started is auto-advanced to in_progress.

    Returns the formatted context string, or None if no persona exists.
    """
    persona = await get_persona_for_agent(db, agent_id)
    if not persona:
        return None

    sections: list[str] = []
    phase = persona.onboarding_phase

    onboarding_section = _build_onboarding_section(persona)
    if onboarding_section:
        sections.append(onboarding_section)
        if phase == "not_started":
            persona.onboarding_phase = "in_progress"
            await db.flush()
            logger.info("Persona onboarding bootstrap injected; phase → in_progress")
        elif phase == "in_progress" and not persona.user_context:
            logger.info("Persona onboarding re-bootstrapped (no prior context)")

    sections.append(f'<identity name="{persona.name}" />')

    if persona.personality:
        sections.append(f"<personality>\n{persona.personality}\n</personality>")

    if persona.heartbeat_instructions:
        sections.append(
            f"<heartbeat_instructions>\n{persona.heartbeat_instructions}\n</heartbeat_instructions>"
        )

    if persona.user_context:
        sections.append(f"<user_context>\n{persona.user_context}\n</user_context>")

    from app.services.memory.repository import get_memory_repository

    repo = get_memory_repository()
    since_dt = datetime.now(UTC) - timedelta(days=journal_days)
    journal_memories = await repo.list_by_scope_and_tier(
        scope="agent:persona",
        memory_type="journal",
        status="active",
        since=since_dt,
        order_by="created_at",
        limit=get_persona_limit(persona, "max_journal_entries"),
    )
    if journal_memories:
        sections.append(_format_journal_section(journal_memories))

    if phase == "complete":
        sections.append(f"<evolution_guidelines>\n{EVOLUTION_TRIGGERS}\n</evolution_guidelines>")

    return "\n\n".join(sections)


async def submit_and_review_onboarding(
    db: AsyncSession,
    summary: str,
    user_context_snapshot: str | None,
) -> dict[str, str]:
    """Submit onboarding for dual-model approval (Opus + Gemini 3.1 Pro).

    Sets phase to pending_approval, runs two reviewers sequentially,
    and either completes onboarding or sends it back for revision.

    Returns dict with 'status' ('approved'|'rejected') and 'feedback'.
    """
    from app.api.complete.core import complete_internal
    from app.constants import REASONING_CLAUDE_MODEL, REASONING_GEMINI_MODEL
    from app.db import async_session

    persona = await get_persona(db)
    if not persona:
        return {"status": "rejected", "feedback": "No persona found."}

    persona.onboarding_attempts += 1
    persona.onboarding_phase = "pending_approval"
    await db.commit()
    logger.info(
        "Onboarding submitted for review (attempt %d); phase → pending_approval",
        persona.onboarding_attempts,
    )

    max_attempts = get_persona_limit(persona, "max_onboarding_attempts")
    if persona.onboarding_attempts >= max_attempts:
        persona.onboarding_phase = "complete"
        persona.onboarding_complete = True
        await db.commit()
        logger.info(
            "Onboarding auto-approved after %d attempts (max=%d)",
            persona.onboarding_attempts, max_attempts,
        )
        return {
            "status": "approved",
            "feedback": f"Auto-approved after {persona.onboarding_attempts} attempts.",
        }

    profile_text = f"## Onboarding Summary\n\n{summary}"
    if user_context_snapshot:
        profile_text += f"\n\n## User Context Snapshot\n\n{user_context_snapshot}"
    review_prompt = build_review_prompt(persona.name, profile_text)

    reviews: list[dict[str, str]] = []
    try:
        for model_id, provider in [
            (REASONING_CLAUDE_MODEL, "claude"),
            (REASONING_GEMINI_MODEL, "gemini"),
        ]:
            review = await run_single_review(
                complete_internal, async_session, model_id, provider, review_prompt, max_retries=2
            )
            reviews.append(review)
    except Exception as e:
        logger.exception("Unexpected error during onboarding review")
        persona.onboarding_phase = "in_progress"
        await db.commit()
        return {"status": "rejected", "feedback": f"Review error: {e}"}

    combined_feedback = "\n\n---\n\n".join(
        f"**{r['model']}**: {r['content']}" for r in reviews
    )

    if all(r["approved"] == "yes" for r in reviews):
        persona.onboarding_phase = "complete"
        persona.onboarding_complete = True
        await db.commit()
        logger.info("Onboarding approved by both reviewers; phase → complete")
        return {"status": "approved", "feedback": combined_feedback}

    persona.onboarding_phase = "in_progress"
    await db.commit()
    logger.info("Onboarding rejected; phase → in_progress for revision")
    return {"status": "rejected", "feedback": combined_feedback}


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
    )
    db.add(persona)
    await db.commit()
    await db.refresh(persona)
    logger.info("Created default persona for agent %s", agent.slug)
    return persona
