"""Persona onboarding review logic — dual-model approval gate."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.persona import Persona
from app.services._persona_crud import get_persona
from app.services._persona_templates import run_single_review
from app.services.persona_prompt_service import render_persona_onboarding_review_prompt

logger = logging.getLogger(__name__)

# Two existing catalog agents keep the dual-review gate route-independent:
# `reviewer` supplies the review discipline and `chat` supplies an independent
# general reading without hardcoding either model or provider here.
_ONBOARDING_REVIEWER_AGENT_SLUGS = ("reviewer", "chat")


async def _check_auto_approve(db: AsyncSession, persona: Persona) -> dict[str, str] | None:
    """If max attempts reached, auto-approve and return result dict; else None."""
    if persona.onboarding_attempts < 3:
        return None
    persona.onboarding_phase = "complete"
    persona.onboarding_complete = True
    await db.commit()
    logger.info(
        "Onboarding auto-approved after %d attempts (max=%d)",
        persona.onboarding_attempts,
        3,
    )
    return {
        "status": "approved",
        "feedback": f"Auto-approved after {persona.onboarding_attempts} attempts.",
    }


async def _apply_review_outcome(
    db: AsyncSession, persona: Persona, reviews: list[dict[str, str]]
) -> dict[str, str]:
    """Persist approval/rejection outcome and return the result dict."""
    combined_feedback = "\n\n---\n\n".join(
        f"**{r['model']}**: {r['content']}" for r in reviews
    )
    if all(r["approved"] == "yes" for r in reviews):
        persona.onboarding_phase = "complete"
        persona.onboarding_complete = True
        await db.commit()
        logger.info("Onboarding approved by both reviewers; phase → complete")
        return {"status": "approved", "feedback": combined_feedback}

    failed_models = [r["model"] for r in reviews if r["content"].startswith("Review failed after")]
    persona.onboarding_phase = "in_progress"
    await db.commit()
    if failed_models:
        logger.warning(
            "Onboarding review had system errors for %s; phase → in_progress for retry",
            ", ".join(failed_models),
        )
        return {"status": "error", "feedback": combined_feedback}
    logger.info("Onboarding rejected by reviewers; phase → in_progress for revision")
    return {"status": "rejected", "feedback": combined_feedback}


def _build_profile_text(summary: str, user_context_snapshot: str | None) -> str:
    """Compose the profile text passed to review models."""
    text = f"## Onboarding Summary\n\n{summary}"
    if user_context_snapshot:
        text += f"\n\n## User Context Snapshot\n\n{user_context_snapshot}"
    return text


async def submit_and_review_onboarding(
    db: AsyncSession,
    summary: str,
    user_context_snapshot: str | None,
) -> dict[str, str]:
    """Submit for dual-model review; returns dict with 'status' and 'feedback'."""
    from app.api.complete.core import complete_internal
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

    auto_result = await _check_auto_approve(db, persona)
    if auto_result:
        return auto_result

    review_prompt = await render_persona_onboarding_review_prompt(
        persona.name,
        _build_profile_text(summary, user_context_snapshot),
    )
    try:
        reviews = list(
            await asyncio.gather(
                *(
                    run_single_review(
                        complete_internal,
                        async_session,
                        agent_slug,
                        review_prompt,
                        max_retries=2,
                    )
                    for agent_slug in _ONBOARDING_REVIEWER_AGENT_SLUGS
                )
            )
        )
    except Exception as e:
        logger.exception("Unexpected error during onboarding review")
        persona.onboarding_phase = "in_progress"
        await db.commit()
        return {"status": "rejected", "feedback": f"Review error: {e}"}

    return await _apply_review_outcome(db, persona, reviews)
