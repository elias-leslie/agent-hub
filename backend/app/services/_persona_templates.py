"""Fallback defaults and onboarding review helper utilities for persona_service."""

from __future__ import annotations

import asyncio
import logging
import re

from app.services.agent_routing_utils import inject_agent_mandates, resolve_agent

logger = logging.getLogger(__name__)


async def run_single_review(
    complete_internal,
    async_session,
    agent_slug: str,
    review_prompt: str,
    max_retries: int,
) -> dict[str, str]:
    """Run one catalog-owned reviewer agent. Returns a review result dict."""
    last_error: Exception | None = None
    reviewer_label = agent_slug
    for attempt in range(max_retries + 1):
        try:
            async with async_session() as review_db:
                resolved = await resolve_agent(agent_slug, review_db)
                mandate = await inject_agent_mandates(
                    resolved.agent,
                    review_db,
                    prompt_mode="minimal",
                    project_id="agent-hub",
                    task_type="review",
                )
                messages: list[dict[str, str]] = []
                if mandate.system_content:
                    messages.append(
                        {"role": "system", "content": mandate.system_content}
                    )
                messages.append({"role": "user", "content": review_prompt})
                reviewer_label = f"{agent_slug} ({resolved.model})"
                result = await complete_internal(
                    messages=messages,
                    model=resolved.model,
                    provider=resolved.provider,
                    temperature=resolved.agent.temperature,
                    project_id="agent-hub",
                    db=review_db,
                    agent_slug=agent_slug,
                    request_source="persona_onboarding_review",
                    use_memory=False,
                    max_turns=1,
                    skip_cache=True,
                    task_type="review",
                    requested_model=resolved.model,
                    requested_provider=resolved.provider,
                )
            content = result.content.strip()
            approved = bool(re.match(r"^\s*APPROVED\b", content, re.IGNORECASE))
            return {
                "model": reviewer_label,
                "approved": "yes" if approved else "no",
                "content": content,
            }
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                logger.warning(
                    "Onboarding review attempt %d/%d failed for %s: %s; retrying",
                    attempt + 1,
                    max_retries + 1,
                    agent_slug,
                    exc,
                )
                await asyncio.sleep(5 * (attempt + 1))

    logger.error(
        "Onboarding review failed for %s after %d attempts: %s",
        agent_slug,
        max_retries + 1,
        last_error,
    )
    return {
        "model": reviewer_label,
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
