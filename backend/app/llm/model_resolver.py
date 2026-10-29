"""Resolve a catalog model-id string into a pi-mono ``Model[Api]``.

The legacy ``app.constants.catalog`` carries provider+scores+capabilities but
not the pi-mono ``api`` discriminator or ``base_url``. This module bridges
the gap: given a provider + model-id, derive the universal ``Model``
the new pipeline's adapters consume.

Phase 5 removes the legacy ``ModelEntry`` shape entirely; this module is
the transitional surface.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

from app.constants.catalog import (
    INACTIVE_MODEL_CATALOG_BY_ID,
    MODEL_CATALOG_BY_ID,
    ModelEntry,
    resolve_model,
)
from app.llm.types import Api, Model, ModelCost, OpenAICompletionsCompat, ThinkingLevelMap

logger = logging.getLogger(__name__)

# Stand-ins for a model the catalog does not know (logged when used).
_UNCATALOGUED_CONTEXT_WINDOW = 128_000
_UNCATALOGUED_MAX_TOKENS = 8192

# Provider wire defaults (API, base URL, per-API base URLs) are data: provider_endpoints.json.
_ENDPOINTS = json.loads((Path(__file__).parent / "provider_endpoints.json").read_text())
_DEFAULT_API: Api = _ENDPOINTS["default_api"]
_PROVIDER_API: dict[str, Api] = {
    name: row["api"] for name, row in _ENDPOINTS["providers"].items() if "api" in row
}
_PROVIDER_BASE_URL: dict[str, str] = {
    name: row["base_url"] for name, row in _ENDPOINTS["providers"].items() if "base_url" in row
}
# (provider, api) → base URL for a provider that serves more than one API; a model's catalog ``api`` picks the row.
_PROVIDER_API_BASE_URL: dict[tuple[str, str], str] = {
    (name, api): url
    for name, row in _ENDPOINTS["providers"].items()
    for api, url in row.get("api_base_urls", {}).items()
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
    entry = _catalog_entry(resolved_id, model_id, provider)
    if entry is not None and entry.upstream_id:
        upstream_id = entry.upstream_id
    api = (entry.api if entry is not None else None) or _PROVIDER_API.get(provider, _DEFAULT_API)
    base_url = _PROVIDER_API_BASE_URL.get((provider, api)) or _resolve_base_url(provider)
    headers = _provider_headers(provider)

    if entry is None:
        # Catalog miss: nothing says what this model supports, so the adapter gets conservative stand-ins.
        logger.warning(
            "model %r (provider %s) is not in the model catalog; assuming context_window=%d and max_tokens=%d",
            model_id, provider, _UNCATALOGUED_CONTEXT_WINDOW, _UNCATALOGUED_MAX_TOKENS,
        )
        return Model(
            id=upstream_id,
            name=resolved_id,
            api=api,
            provider=provider,
            base_url=base_url,
            reasoning=False,
            input=["text"],
            cost=ModelCost(input=0.0, output=0.0, cache_read=0.0, cache_write=0.0),
            context_window=_UNCATALOGUED_CONTEXT_WINDOW,
            max_tokens=_UNCATALOGUED_MAX_TOKENS,
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
        compat=_provider_compat(provider, entry.family, base_url, api),
    )


def _catalog_entry(resolved_id: str, model_id: str, provider: str) -> ModelEntry | None:
    """The catalog row for a model: active, then inactive, then the one whose provider-side id matches."""
    entry = MODEL_CATALOG_BY_ID.get(resolved_id) or INACTIVE_MODEL_CATALOG_BY_ID.get(resolved_id)
    if entry is not None:
        return entry
    bare = model_id.removeprefix(f"{provider}/")
    for candidate in (*MODEL_CATALOG_BY_ID.values(), *INACTIVE_MODEL_CATALOG_BY_ID.values()):
        if candidate.provider == provider and bare in (candidate.upstream_id, candidate.id.removeprefix(f"{provider}/")):
            return candidate
    return None


def _provider_headers(provider: str) -> dict[str, str] | None:
    if provider in {"kimi-code", "kimi-coding"}:
        return {"User-Agent": "KimiCLI/1.5"}
    if provider == "opencode-go":
        # OpenCode Go rejects inference requests (400 MissingSessionID) without a session header.
        from app.services.subscription_accounting.opencode_go import install_session_id

        return {"x-opencode-session": install_session_id()}
    return None


def _provider_compat(provider: str, family: str | None, base_url: str, api: str) -> OpenAICompletionsCompat | None:
    if provider == "local" and family == "qwen":
        return _local_qwen_compat(base_url)
    if provider == "opencode-go" and api == "openai-completions":
        return _opencode_go_compat(family)
    return None


def _opencode_go_compat(family: str | None) -> OpenAICompletionsCompat:
    """OpenCode Go's OpenAI-compatible gateway, as Pi configures it; DeepSeek models also take DeepSeek's thinking wire format."""
    deepseek = family == "deepseek"
    return OpenAICompletionsCompat(
        supports_store=False,
        supports_developer_role=False,
        supports_strict_mode=True,
        max_tokens_field="max_tokens",
        thinking_format="deepseek" if deepseek else None,
        requires_reasoning_content_on_assistant_messages=True if deepseek else None,
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
