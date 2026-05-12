"""Resolve a catalog model-id string into a pi-mono ``Model[Api]``.

The legacy ``app.constants.catalog`` carries provider+scores+capabilities but
not the pi-mono ``api`` discriminator or ``base_url``. This module bridges
the gap: given a provider + model-id, derive the universal ``Model``
the new pipeline's adapters consume.

Phase 5 removes the legacy ``ModelEntry`` shape entirely; this module is
the transitional surface.
"""

from __future__ import annotations

from app.constants.catalog import MODEL_CATALOG_BY_ID, resolve_model
from app.llm.types import Api, Model, ModelCost

# Provider → API id mapping. Matches the three providers ported in Phase 1+2.
_PROVIDER_API: dict[str, Api] = {
    "anthropic": "anthropic-messages",
    "claude": "anthropic-messages",
    "google": "google-generative-ai",
    "gemini": "google-generative-ai",
    # Everything OpenAI-compatible collapses here per D4.
    "openai": "openai-completions",
    "openrouter": "openai-completions",
    "xai": "openai-completions",
    "zhipu": "openai-completions",
    "minimax": "openai-completions",
    "kimi-code": "openai-completions",
    "moonshot": "openai-completions",
    "moonshotai": "openai-completions",
    "deepseek": "openai-completions",
    "local": "openai-completions",
    "nvidia": "openai-completions",
    "cloudflare": "openai-completions",
    "codex": "anthropic-messages",  # codex = Anthropic OAuth per D7
}

# Provider → default base URL. Per-model overrides happen via Model.base_url.
_PROVIDER_BASE_URL: dict[str, str] = {
    "anthropic": "https://api.anthropic.com",
    "claude": "https://api.anthropic.com",
    "google": "https://generativelanguage.googleapis.com",
    "gemini": "https://generativelanguage.googleapis.com",
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "xai": "https://api.x.ai/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "minimax": "https://api.minimaxi.com/v1",
    "kimi-code": "https://api.moonshot.ai/v1",
    "moonshot": "https://api.moonshot.ai/v1",
    "moonshotai": "https://api.moonshot.ai/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "local": "http://localhost:8080/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "cloudflare": "",  # filled per-account at runtime
    "codex": "https://api.anthropic.com",
}


def resolve_llm_model(model_id: str, provider: str) -> Model[Api]:
    """Build a pi-mono ``Model[Api]`` from the legacy catalog.

    ``model_id`` is the resolved (alias-expanded) model id; ``provider`` is the
    provider name from ``app.services.agent_routing.get_provider_for_model``.
    """
    resolved_id = resolve_model(model_id)
    entry = MODEL_CATALOG_BY_ID.get(resolved_id)
    api = _PROVIDER_API.get(provider, "openai-completions")
    base_url = _PROVIDER_BASE_URL.get(provider, "")

    if entry is None:
        # Catalog miss — return a minimal Model so the adapter can still try.
        return Model(
            id=resolved_id,
            name=resolved_id,
            api=api,
            provider=provider,
            base_url=base_url,
            reasoning=False,
            input=["text"],
            cost=ModelCost(input=0.0, output=0.0, cache_read=0.0, cache_write=0.0),
            context_window=128_000,
            max_tokens=8192,
        )

    caps = entry.capabilities
    inputs: list = ["text"] + (["image"] if caps.has_vision else [])
    return Model(
        id=resolved_id,
        name=entry.name,
        api=api,
        provider=provider,
        base_url=base_url,
        reasoning=bool(caps.has_thinking),
        input=inputs,
        cost=ModelCost(
            input=entry.cost.input_per_m,
            output=entry.cost.output_per_m,
            cache_read=entry.cost.cache_read_per_million or 0.0,
            cache_write=entry.cost.cache_write_per_million or 0.0,
        ),
        context_window=entry.context_window,
        max_tokens=caps.max_output_tokens,
    )


__all__ = ["resolve_llm_model"]
