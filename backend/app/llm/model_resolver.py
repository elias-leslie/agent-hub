"""Resolve a catalog model-id string into a pi-mono ``Model[Api]``.

The legacy ``app.constants.catalog`` carries provider+scores+capabilities but
not the pi-mono ``api`` discriminator or ``base_url``. This module bridges
the gap: given a provider + model-id, derive the universal ``Model``
the new pipeline's adapters consume.

Phase 5 removes the legacy ``ModelEntry`` shape entirely; this module is
the transitional surface.
"""

from __future__ import annotations

from typing import cast
from urllib.parse import urlparse

from app.constants.catalog import MODEL_CATALOG_BY_ID, resolve_model
from app.llm.provider_support.cloudflare import CLOUDFLARE_WORKERS_AI_BASE_URL
from app.llm.types import Api, Model, ModelCost, OpenAICompletionsCompat, ThinkingLevelMap

# Provider → API id mapping. Matches the three providers ported in Phase 1+2.
_PROVIDER_API: dict[str, Api] = {
    "google": "google-generative-ai",
    "gemini": "google-generative-ai",
    # Everything OpenAI-compatible collapses here per D4.
    "openai": "openai-completions",
    "openrouter": "openai-completions",
    "xai": "openai-completions",
    "zhipu": "openai-completions",
    "minimax": "anthropic-messages",
    "minimax-cn": "anthropic-messages",
    "kimi-code": "anthropic-messages",
    "kimi-coding": "anthropic-messages",
    "moonshot": "openai-completions",
    "moonshotai": "openai-completions",
    "deepseek": "openai-completions",
    "local": "openai-completions",
    "nvidia": "openai-completions",
    "cloudflare": "openai-completions",
    "codex": "openai-codex-responses",
    # Claude runs through the headless Claude Code CLI on the owner's subscription.
    "claude": "claude-code-cli",
}

# Provider → default base URL. Per-model overrides happen via Model.base_url.
_PROVIDER_BASE_URL: dict[str, str] = {
    "google": "",
    "gemini": "",
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "xai": "https://api.x.ai/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "minimax": "https://api.minimax.io/anthropic",
    "minimax-cn": "https://api.minimaxi.com/anthropic",
    "kimi-code": "https://api.kimi.com/coding",
    "kimi-coding": "https://api.kimi.com/coding",
    "moonshot": "https://api.moonshot.ai/v1",
    "moonshotai": "https://api.moonshot.ai/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "local": "http://127.0.0.1:11434/v1",  # Ollama; effective value read from settings.local_openai_base_url
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "cloudflare": CLOUDFLARE_WORKERS_AI_BASE_URL,
    "codex": "https://chatgpt.com/backend-api/codex/responses",
    "claude": "",
}


def resolve_llm_model(
    model_id: str,
    provider: str,
) -> Model[Api]:
    """Build a pi-mono ``Model[Api]`` from the legacy catalog.

    ``model_id`` is the resolved (alias-expanded) model id; ``provider`` is the
    provider name from ``app.services.agent_routing.get_provider_for_model``.
    """
    resolved_id = resolve_model(model_id)
    upstream_id = upstream_model_id(resolved_id, provider)
    entry = MODEL_CATALOG_BY_ID.get(resolved_id)
    api = _PROVIDER_API.get(provider, "openai-completions")
    base_url = _resolve_base_url(provider)
    headers = {"User-Agent": "KimiCLI/1.5"} if provider in {"kimi-code", "kimi-coding"} else None

    if entry is None:
        # Catalog miss — return a minimal Model so the adapter can still try.
        return Model(
            id=upstream_id,
            name=resolved_id,
            api=api,
            provider=provider,
            base_url=base_url,
            reasoning=False,
            input=["text"],
            cost=ModelCost(input=0.0, output=0.0, cache_read=0.0, cache_write=0.0),
            context_window=128_000,
            max_tokens=8192,
            headers=headers,
        )

    caps = entry.capabilities
    inputs: list = (
        ["text"]
        + (["image"] if caps.has_vision else [])
        + (["audio"] if caps.supports_audio else [])
    )
    return Model(
        id=upstream_id,
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
        thinking_level_map=cast(ThinkingLevelMap | None, caps.thinking_level_map),
        headers=headers,
        access_programs=entry.access_programs,
        compat=(
            _local_qwen_compat(base_url)
            if provider == "local" and entry.family == "qwen"
            else None
        ),
    )


def _local_qwen_compat(base_url: str) -> OpenAICompletionsCompat:
    """Use Ollama's effort API on its endpoint; retain llama.cpp template controls."""
    is_ollama = urlparse(base_url).port == 11434
    return OpenAICompletionsCompat(
        supports_store=False,
        supports_developer_role=False,
        supports_reasoning_effort=is_ollama,
        supports_usage_in_streaming=True,
        max_tokens_field="max_tokens",
        thinking_format="qwen-chat-template",
        supports_strict_mode=False,
        supports_long_cache_retention=False,
        reasoning_budget_tokens=(
            None if is_ollama else {"low": 512, "medium": 1_024, "xhigh": 2_048}
        ),
        loopback_only_transport=True,
    )


def upstream_model_id(model_id: str, provider: str) -> str:
    """Return the provider-side id: the catalog ``upstream_id`` or the id minus its prefix."""
    entry = MODEL_CATALOG_BY_ID.get(resolve_model(model_id))
    if entry is not None and entry.upstream_id:
        return entry.upstream_id
    prefix = f"{provider}/"
    return model_id[len(prefix):] if model_id.startswith(prefix) else model_id


def _resolve_base_url(provider: str) -> str:
    if provider == "local":
        # Single source of truth for the local OpenAI-compatible endpoint (Ollama).
        from app.config import settings

        return settings.local_openai_base_url
    base_url = _PROVIDER_BASE_URL.get(provider, "")
    if provider != "cloudflare" or "{" not in base_url:
        return base_url

    from app.llm.provider_support.cloudflare import resolve_cloudflare_base_url

    return resolve_cloudflare_base_url(
        Model(
            id="",
            name="",
            api="openai-completions",
            provider=provider,
            base_url=base_url,
            reasoning=False,
            input=["text"],
            cost=ModelCost(input=0.0, output=0.0, cache_read=0.0, cache_write=0.0),
            context_window=0,
            max_tokens=0,
        )
    )


__all__ = ["resolve_llm_model"]
