"""Reviewer-agent completion call for memory review batches."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import AuthenticationError, ProviderError, RateLimitError

from ._review_agent_prompt import REVIEW_SCHEMA

logger = logging.getLogger(__name__)


async def _call_reviewer_agent(
    db: AsyncSession,
    *,
    reviewer_agent_slug: str,
    prompt: str,
    reviewer_model_id: str | None = None,
) -> tuple[str, str | None, str | None]:
    from app.services.agent_routing import get_provider_for_model
    from app.services.agent_routing_utils import inject_agent_mandates, resolve_agent

    resolved = await resolve_agent(reviewer_agent_slug, db)
    mandate = await inject_agent_mandates(
        resolved.agent,
        db,
        prompt_mode="minimal",
        project_id="agent-hub",
        task_type="review",
    )
    messages = _reviewer_messages(mandate.system_content, prompt)
    candidate_models = [
        *([reviewer_model_id] if reviewer_model_id else []),
        resolved.model,
        *list(resolved.agent.fallback_models or []),
    ]
    last_error: Exception | None = None
    for model in dict.fromkeys(candidate_models):
        provider = resolved.provider if model == resolved.model else get_provider_for_model(model)
        try:
            result = await _complete_review_with_model(
                db=db,
                messages=messages,
                model=model,
                provider=provider,
                resolved=resolved,
                reviewer_agent_slug=reviewer_agent_slug,
            )
            return result.content, model, result.session_id
        except Exception as exc:
            last_error = exc
            if isinstance(exc, AuthenticationError):
                raise
            if not isinstance(exc, RateLimitError) and not (
                isinstance(exc, ProviderError) and exc.retriable
            ):
                raise
            logger.warning("Memory review model %s failed; trying fallback: %s", model, exc)
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"No reviewer models configured for {reviewer_agent_slug}")


def _reviewer_messages(system_content: str | None, prompt: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if system_content:
        messages.append({"role": "system", "content": system_content})
    messages.append({"role": "user", "content": prompt})
    return messages


async def _complete_review_with_model(
    *,
    db: AsyncSession,
    messages: list[dict[str, Any]],
    model: str,
    provider: str,
    resolved: Any,
    reviewer_agent_slug: str,
) -> Any:
    from app.api.complete.core import complete_internal

    return await complete_internal(
        messages=messages,
        model=model,
        provider=provider,
        temperature=resolved.agent.temperature,
        project_id="agent-hub",
        db=db,
        agent_slug=reviewer_agent_slug,
        request_source="memory_review",
        use_memory=False,
        enable_caching=False,
        skip_cache=True,
        max_turns=1,
        execute_tools=False,
        thinking_level=resolved.agent.thinking_level,
        response_format={"type": "json_object", "schema": REVIEW_SCHEMA},
        task_type="review",
        phase="memory_review",
    )


__all__ = ["_call_reviewer_agent"]
