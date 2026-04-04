"""Reconcile seeded text-agent model chains to the providers actually available."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.registry import get_provider_for_model
from app.config import settings
from app.constants import OR_FREE_GLM, resolve_model
from app.models import Agent
from app.services.agent_cache import AgentCache
from app.services.credential_manager import get_credential_manager
from app.services.model_mapping import map_model_to_provider

logger = logging.getLogger(__name__)

TEXT_PROVIDER_PRIORITY = ("codex", "claude", "openai", "gemini", "openrouter")
SKIP_AGENT_SLUGS = {"image-gen"}


def _unique_models(models: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for model in models:
        if not model or model in seen:
            continue
        seen.add(model)
        ordered.append(model)
    return ordered


def _provider_available(provider: str) -> bool:
    credential_manager = get_credential_manager()

    if provider == "codex":
        return bool(credential_manager.get("codex", "oauth_token"))
    if provider == "claude":
        return bool(
            credential_manager.get("claude", "oauth_token")
            or credential_manager.get_api_key("claude")
        )
    if provider == "gemini":
        return bool(credential_manager.get_api_keys("gemini"))
    return bool(credential_manager.get_api_key(provider))


def _available_text_providers() -> list[str]:
    return [
        provider
        for provider in TEXT_PROVIDER_PRIORITY
        if _provider_available(provider)
    ]


def _map_model(model_id: str, target_provider: str) -> str:
    resolved = resolve_model(model_id)
    if target_provider == "openrouter":
        return OR_FREE_GLM
    return resolve_model(map_model_to_provider(resolved, target_provider))


def _source_chain(agent: Agent) -> list[str]:
    models = [agent.primary_model_id, *(agent.fallback_models or [])]
    if agent.escalation_model_id:
        models.append(agent.escalation_model_id)
    return _unique_models([resolve_model(model) for model in models if model])


def _target_chain(agent: Agent, available_providers: list[str]) -> list[str]:
    original_chain = _source_chain(agent)
    available_chain = [
        model
        for model in original_chain
        if get_provider_for_model(model) in available_providers
    ]

    for model in original_chain:
        if get_provider_for_model(model) in available_providers:
            continue
        for provider in available_providers:
            available_chain.append(_map_model(model, provider))

    if not available_chain:
        for provider in available_providers:
            available_chain.append(_map_model(agent.primary_model_id, provider))

    return _unique_models(available_chain)


async def _invalidate_agent_cache(slugs: list[str]) -> None:
    cache = AgentCache(settings.agent_hub_redis_url)
    try:
        for slug in slugs:
            await cache.invalidate(slug)
    finally:
        await cache.close()


async def reconcile_agent_models_to_available_providers(
    db: AsyncSession,
) -> list[str]:
    """Promote available text providers into seeded agent model chains.

    Clean installs often provide provider API keys via `.env` instead of through
    the dashboard credential UI. This service ensures seeded text agents remain
    usable in that configuration by reordering or remapping their model chains
    to providers that are actually configured.
    """

    available_providers = _available_text_providers()
    if not available_providers:
        logger.info("No text-model providers configured for startup reconciliation")
        return []

    result = await db.execute(
        select(Agent).where(Agent.is_active == True).order_by(Agent.slug)  # noqa: E712
    )
    agents = result.scalars().all()

    changed_slugs: list[str] = []
    for agent in agents:
        if agent.slug in SKIP_AGENT_SLUGS:
            continue

        current_primary = resolve_model(agent.primary_model_id)
        current_fallbacks = _unique_models(
            [resolve_model(model) for model in (agent.fallback_models or []) if model]
        )
        current_escalation = (
            resolve_model(agent.escalation_model_id)
            if agent.escalation_model_id
            else None
        )

        target_chain = _target_chain(agent, available_providers)
        if not target_chain:
            continue

        target_primary = target_chain[0]
        target_fallbacks = target_chain[1:4]
        target_escalation = None
        if agent.escalation_model_id:
            target_escalation = next(
                (model for model in target_chain if model != target_primary),
                target_primary,
            )

        if (
            target_primary == current_primary
            and target_fallbacks == current_fallbacks
            and target_escalation == current_escalation
        ):
            continue

        agent.primary_model_id = target_primary
        agent.fallback_models = target_fallbacks
        agent.escalation_model_id = target_escalation
        changed_slugs.append(agent.slug)

    if not changed_slugs:
        return []

    await db.commit()
    await _invalidate_agent_cache(changed_slugs)
    return changed_slugs
