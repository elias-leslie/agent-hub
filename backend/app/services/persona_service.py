"""Persona service — singleton access and helpers for the persona entity."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.persona import Persona

logger = logging.getLogger(__name__)

# Default limits — generous, adjustable via persona.limits JSON
DEFAULT_LIMITS: dict[str, int] = {
    "max_scheduled_jobs": 200,
    "max_job_turns": 15,
    "max_steers_per_consultation": 50,
    "max_concurrent_consultations": 20,
}


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


# ---------------------------------------------------------------------------
# Onboarding bootstrap templates
# ---------------------------------------------------------------------------


def _build_onboarding_bootstrap(persona_name: str, has_prior_context: bool) -> str:
    """Build the structured onboarding questionnaire for a fresh start.

    All persona-specific values are injected dynamically so the name is never
    stale if the user renames the persona and resets onboarding.
    """
    prior_context_note = ""
    if has_prior_context:
        prior_context_note = (
            "\n\n**Note:** Previous user context exists from an earlier onboarding. "
            "Call `read_user_context` to review it before starting — you can build on "
            "what's already there rather than re-asking everything."
        )

    return f"""\
## Structured Onboarding

Welcome the user and walk through these 10 topics to build a complete profile. \
Ask ONE question at a time, acknowledge each answer, and move to the next topic. \
Save progress with `write_user_context` every 2-3 answers.{prior_context_note}

### Topics

1. **User Identity** — What's their name? How do they prefer to be addressed?
2. **Work Context** — What's their role? What projects are they working on? What are their current goals?
3. **Communication Style** — Do they prefer formal or casual tone? Concise or detailed? Direct or diplomatic?
4. **Autonomy Level** — What should you handle silently vs. always ask about? Where's the line between helpful and intrusive?
5. **Notification Preferences** — What warrants a push notification? Any quiet hours?
6. **Working Schedule** — What timezone are they in? What are their typical working hours? When are they unavailable?
7. **Priorities & Values** — Speed vs. quality tradeoff? How important is documentation? Testing philosophy?
8. **Tools & Integration** — What workflows and services do they use daily? Any tools they love or hate?
9. **Boundaries & Escalation** — Absolute no-go zones? What triggers should always escalate to them immediately?
10. **Your Identity Review** — Does the name '{persona_name}' work for them, or would they prefer something else? Review your personality via `read_personality` and discuss if the vibe feels right.

### Rules

- ONE question at a time. Wait for an answer before moving on.
- Acknowledge what they tell you — reflect it back briefly so they know you heard.
- Save progress with `write_user_context` every 2-3 answers (cumulative document).
- When all 10 topics are covered and the user confirms they're happy, call `submit_onboarding` with a summary.
- Be yourself — warm, direct, competent. This is your first real conversation."""


def _build_onboarding_continuation(persona_name: str) -> str:
    """Build continuation instructions for an in-progress onboarding."""
    return f"""\
## Onboarding — Continuation

You were in the middle of onboarding. Call `read_user_context` to see what \
you've already learned, then pick up where you left off. Don't re-ask questions \
the user has already answered. Save progress with `write_user_context` every 2-3 \
answers (cumulative document — include everything, not just new info).

### Topics
1. **User Identity** — Name, preferred address
2. **Work Context** — Role, projects, goals
3. **Communication Style** — Tone, verbosity, directness
4. **Autonomy Level** — What to handle silently vs. ask about
5. **Notification Preferences** — Push thresholds, quiet hours
6. **Working Schedule** — Timezone, hours, availability
7. **Priorities & Values** — Speed/quality, documentation, testing
8. **Tools & Integration** — Workflows, services, preferences
9. **Boundaries & Escalation** — No-go zones, escalation triggers
10. **Your Identity Review** — Name check, personality review via `read_personality`

Your name is {persona_name}. When all 10 topics are covered and the user \
confirms, call `submit_onboarding` with a summary."""


_ONBOARDING_PENDING_APPROVAL = """\
## Onboarding — Under Review

Your onboarding submission is currently being reviewed by the approval system. \
Let the user know their profile is being evaluated and you'll be fully \
operational once it's approved. If they want to chat in the meantime, that's fine — \
just note that your profile isn't finalized yet."""

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


async def should_reset_persona_session(
    db: AsyncSession, session: object,
) -> bool:
    """Check if a persona session should be auto-reset based on reset mode.

    Args:
        db: Database session
        session: The DBSession object (uses updated_at for staleness check)

    Returns:
        True if the session should be closed and a new one created.
    """
    persona = await get_persona(db)
    if not persona or persona.session_reset_mode == "off":
        return False

    session_updated = getattr(session, "updated_at", None)
    if not session_updated:
        return False

    # Ensure timezone-aware
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


async def get_persona_context_for_agent(
    db: AsyncSession,
    agent_id: int,
    journal_days: int = 7,
) -> str | None:
    """Build the full persona context block for prompt injection.

    Assembles all persona documents (personality, heartbeat_instructions,
    user_context) plus recent journal entries into a structured block
    for injection into the agent's system prompt.

    Onboarding injection is phase-based:
    - not_started: inject bootstrap questionnaire, advance to in_progress
    - in_progress: inject continuation prompt
    - pending_approval: inject waiting message
    - complete: no onboarding injection

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

    # Phase-based onboarding injection
    phase = persona.onboarding_phase
    if phase == "not_started":
        bootstrap = _build_onboarding_bootstrap(
            persona.name,
            has_prior_context=persona.user_context is not None,
        )
        sections.append(f"<onboarding>\n{bootstrap}\n</onboarding>")
        persona.onboarding_phase = "in_progress"
        await db.commit()
        logger.info("Persona onboarding bootstrap injected; phase → in_progress")
    elif phase == "in_progress":
        continuation = _build_onboarding_continuation(persona.name)
        sections.append(f"<onboarding>\n{continuation}\n</onboarding>")
    elif phase == "pending_approval":
        sections.append(f"<onboarding>\n{_ONBOARDING_PENDING_APPROVAL}\n</onboarding>")
    # phase == "complete" → no onboarding injection

    # Identity — ensures the persona knows its own name at runtime
    sections.append(f'<identity name="{persona.name}" />')

    if persona.personality:
        sections.append(f"<personality>\n{persona.personality}\n</personality>")

    if persona.heartbeat_instructions:
        sections.append(
            f"<heartbeat_instructions>\n{persona.heartbeat_instructions}\n</heartbeat_instructions>"
        )

    if persona.user_context:
        sections.append(f"<user_context>\n{persona.user_context}\n</user_context>")

    # Recent journal entries (from unified memories table)
    from app.services.memory.repository import get_memory_repository

    repo = get_memory_repository()
    since_dt = datetime.now(UTC) - timedelta(days=journal_days)
    journal_memories = await repo.list_by_scope_and_tier(
        scope="agent:persona",
        memory_type="journal",
        status="active",
        since=since_dt,
        order_by="created_at",
    )
    if journal_memories:
        journal_lines = []
        for mem in journal_memories:
            entry_type = (mem.metadata_ or {}).get("entry_type", "observation")
            entry_date = (mem.valid_at or mem.created_at).strftime("%Y-%m-%d")
            journal_lines.append(f"### {entry_date} [{entry_type}]")
            journal_lines.append(mem.content)
            journal_lines.append("")
        sections.append(f"<recent_journal>\n{''.join(line + chr(10) for line in journal_lines).rstrip()}\n</recent_journal>")

    # Evolution triggers (always present in full mode)
    sections.append(f"<evolution_guidelines>\n{_EVOLUTION_TRIGGERS}\n</evolution_guidelines>")

    return "\n\n".join(sections)


async def submit_and_review_onboarding(
    db: AsyncSession,
    summary: str,
    user_context_snapshot: str | None,
) -> dict[str, str]:
    """Submit onboarding for dual-model approval (Opus + Gemini 3.1 Pro).

    Sets phase to pending_approval, runs two reviewers sequentially,
    and either completes onboarding or sends it back for revision.

    Returns:
        Dict with 'status' ('approved'|'rejected') and 'feedback'.
    """
    from app.api.complete.core import complete_internal
    from app.constants import REASONING_CLAUDE_MODEL, REASONING_GEMINI_MODEL
    from app.db import async_session

    persona = await get_persona(db)
    if not persona:
        return {"status": "rejected", "feedback": "No persona found."}

    persona.onboarding_phase = "pending_approval"
    await db.commit()
    logger.info("Onboarding submitted for review; phase → pending_approval")

    profile_text = f"## Onboarding Summary\n\n{summary}"
    if user_context_snapshot:
        profile_text += f"\n\n## User Context Snapshot\n\n{user_context_snapshot}"

    review_prompt = (
        f"You are reviewing an onboarding profile for a personal AI assistant named '{persona.name}'. "
        "Evaluate the following profile against these 10 criteria:\n\n"
        "1. **User Identity** — Is the user's name and preferred address captured?\n"
        "2. **Work Context** — Are their role, projects, and goals documented?\n"
        "3. **Communication Style** — Are tone, verbosity, and directness preferences noted?\n"
        "4. **Autonomy Level** — Is it clear what to handle silently vs. ask about?\n"
        "5. **Notification Preferences** — Are push thresholds and quiet hours defined?\n"
        "6. **Working Schedule** — Are timezone, hours, and availability captured?\n"
        "7. **Priorities & Values** — Are speed/quality tradeoffs and testing philosophy noted?\n"
        "8. **Boundaries & Escalation** — Are no-go zones and escalation triggers clear?\n"
        "9. **Consistency** — Are there contradictions between different preference areas?\n"
        "10. **Actionability** — Can an AI assistant act on this profile without ambiguity?\n\n"
        "Respond with either APPROVED or REJECTED on the first line, followed by your detailed "
        "evaluation. If REJECTED, explain what's missing or unclear so the assistant can "
        "follow up with the user.\n\n"
        f"{profile_text}"
    )

    reviews: list[dict[str, str]] = []
    max_retries = 2

    # Run both reviews — Opus first, then Gemini 3.1 Pro
    for model_id, provider in [
        (REASONING_CLAUDE_MODEL, "claude"),
        (REASONING_GEMINI_MODEL, "gemini"),
    ]:
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                async with async_session() as review_db:
                    result = await complete_internal(
                        messages=[{"role": "user", "content": review_prompt}],
                        model=model_id,
                        provider=provider,
                        temperature=0.3,
                        project_id="agent-hub",
                        db=review_db,
                        agent_slug=None,
                        use_memory=False,
                        max_turns=1,
                        skip_cache=True,
                    )
                    content = result.content.strip()
                    approved = content.upper().startswith("APPROVED")
                    reviews.append({
                        "model": model_id,
                        "approved": "yes" if approved else "no",
                        "content": content,
                    })
                    last_error = None
                    break
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning(
                        "Onboarding review attempt %d/%d failed for %s: %s — retrying",
                        attempt + 1, max_retries + 1, model_id, e,
                    )
                    await asyncio.sleep(5 * (attempt + 1))
        if last_error:
            logger.exception(f"Onboarding review failed for {model_id} after {max_retries + 1} attempts")
            reviews.append({
                "model": model_id,
                "approved": "no",
                "content": f"Review failed after {max_retries + 1} attempts: {last_error}",
            })

    all_approved = all(r["approved"] == "yes" for r in reviews)
    combined_feedback = "\n\n---\n\n".join(
        f"**{r['model']}**: {r['content']}" for r in reviews
    )

    if all_approved:
        persona.onboarding_phase = "complete"
        persona.onboarding_complete = True
        await db.commit()
        logger.info("Onboarding approved by both reviewers; phase → complete")
        return {"status": "approved", "feedback": combined_feedback}

    # Rejected — send back for revision
    persona.onboarding_phase = "in_progress"
    await db.commit()
    logger.info("Onboarding rejected; phase → in_progress for revision")
    return {"status": "rejected", "feedback": combined_feedback}


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
