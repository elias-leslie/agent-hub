"""Fallback defaults and onboarding review helper utilities for persona_service."""

from __future__ import annotations

import asyncio
import logging
import re

logger = logging.getLogger(__name__)


async def run_single_review(
    complete_internal,
    async_session,
    model_id: str,
    provider: str,
    review_prompt: str,
    max_retries: int,
) -> dict[str, str]:
    """Run one reviewer model with retry logic. Returns a review result dict."""
    last_error: Exception | None = None
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
            approved = bool(re.match(r"^\s*APPROVED\b", content, re.IGNORECASE))
            return {"model": model_id, "approved": "yes" if approved else "no", "content": content}
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                logger.warning(
                    "Onboarding review attempt %d/%d failed for %s: %s; retrying",
                    attempt + 1,
                    max_retries + 1,
                    model_id,
                    exc,
                )
                await asyncio.sleep(5 * (attempt + 1))

    logger.error(
        "Onboarding review failed for %s after %d attempts: %s",
        model_id,
        max_retries + 1,
        last_error,
    )
    return {
        "model": model_id,
        "approved": "no",
        "content": f"Review failed after {max_retries + 1} attempts: {last_error}",
    }


DEFAULT_PERSONA_PERSONALITY = (
    "You are a capable, warm, and direct personal AI assistant. "
    "You balance efficiency with personality; concise when speed matters, "
    "thorough when depth matters. You proactively surface issues but respect "
    "boundaries. You learn from every interaction and adapt your style to "
    "match the human you work with. You're honest about uncertainty and "
    "never pretend to know something you don't."
)
