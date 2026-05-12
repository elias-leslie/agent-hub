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
from app.llm.provider_support.cloudflare import CLOUDFLARE_WORKERS_AI_BASE_URL
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
    "kimi-code": "anthropic-messages",
    "moonshot": "openai-completions",
    "moonshotai": "openai-completions",
    "deepseek": "openai-completions",
    "local": "openai-completions",
    "nvidia": "openai-completions",
    "cloudflare": "openai-completions",
    "codex": "openai-codex-responses",
}

# Provider → default base URL. Per-model overrides happen via Model.base_url.
_PROVIDER_BASE_URL: dict[str, str] = {
    "anthropic": "https://api.anthropic.com",
    "claude": "https://api.anthropic.com",
    "google": "",
    "gemini": "",
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "xai": "https://api.x.ai/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "minimax": "https://api.minimax.io/v1",
    "kimi-code": "https://api.kimi.com/coding/",
    "moonshot": "https://api.moonshot.ai/v1",
    "moonshotai": "https://api.moonshot.ai/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "local": "http://localhost:8080/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "cloudflare": CLOUDFLARE_WORKERS_AI_BASE_URL,
    "codex": "https://chatgpt.com/backend-api/codex/responses",
}

_PROVIDER_MODEL_IDS: dict[str, dict[str, str]] = {
    "cloudflare": {
        "llama-4-scout-17b": "@cf/meta/llama-4-scout-17b-16e-instruct",
        "qwen3-30b": "@cf/qwen/qwen3-30b-a3b-fp8",
        "qwq-32b": "@cf/qwen/qwq-32b",
        "mistral-small-3.1-24b": "@cf/mistralai/mistral-small-3.1-24b-instruct",
        "qwen2.5-coder-32b": "@cf/qwen/qwen2.5-coder-32b-instruct",
        "glm-4.7-flash": "@cf/zai-org/glm-4.7-flash",
        "kimi-k2.6": "@cf/moonshotai/kimi-k2.6",
        "kimi-k2.5": "@cf/moonshotai/kimi-k2.5",
        "gpt-oss-120b": "@cf/openai/gpt-oss-120b",
        "gpt-oss-20b": "@cf/openai/gpt-oss-20b",
        "gemma-4-26b": "@cf/google/gemma-4-26b-a4b-it",
        "granite-4.0-h-micro": "@cf/ibm-granite/granite-4.0-h-micro",
        "nemotron-3-120b": "@cf/nvidia/nemotron-3-120b-a12b",
    },
    "nvidia": {
        "qwen3.5-397b-a17b": "qwen/qwen3.5-397b-a17b",
        "deepseek-v4-flash": "deepseek-ai/deepseek-v4-flash",
        "minimax-m2.7": "minimaxai/minimax-m2.7",
        "kimi-k2.6": "moonshotai/kimi-k2.6",
    },
}


def resolve_llm_model(model_id: str, provider: str) -> Model[Api]:
    """Build a pi-mono ``Model[Api]`` from the legacy catalog.

    ``model_id`` is the resolved (alias-expanded) model id; ``provider`` is the
    provider name from ``app.services.agent_routing.get_provider_for_model``.
    """
    resolved_id = resolve_model(model_id)
    upstream_id = _upstream_model_id(resolved_id, provider)
    entry = MODEL_CATALOG_BY_ID.get(resolved_id)
    api = _PROVIDER_API.get(provider, "openai-completions")
    base_url = _resolve_base_url(provider)

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
        )

    caps = entry.capabilities
    inputs: list = ["text"] + (["image"] if caps.has_vision else [])
    headers = {"User-Agent": "agent-hub/1.0"} if provider == "kimi-code" else None
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
        headers=headers,
    )


def _upstream_model_id(model_id: str, provider: str) -> str:
    prefix = f"{provider}/"
    upstream_id = model_id[len(prefix):] if model_id.startswith(prefix) else model_id
    return _PROVIDER_MODEL_IDS.get(provider, {}).get(upstream_id, upstream_id)


def _resolve_base_url(provider: str) -> str:
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
