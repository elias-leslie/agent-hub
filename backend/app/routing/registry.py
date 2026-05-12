"""Provider routing registry.

This module keeps provider-name validation and model-to-provider lookup out of
``app.adapters``. The pi-mono provider registry lives in ``app.llm``; this file
is only for Agent Hub routing and credential surfaces that still speak legacy
provider names such as ``claude`` or ``gemini``.
"""

from __future__ import annotations

import logging
from typing import Annotated

from pydantic import BeforeValidator

logger = logging.getLogger(__name__)

_INVALIDATED_PROVIDERS: set[str] = set()


def get_provider_for_model(model: str) -> str:
    """Determine provider from model ID using the catalog, with string fallback."""
    from app.constants.catalog import MODEL_CATALOG_BY_ID, resolve_model

    resolved = resolve_model(model)
    entry = MODEL_CATALOG_BY_ID.get(resolved)
    if entry:
        return entry.provider

    model_lower = model.lower()
    prefix_map = [
        ("openrouter/", "openrouter"),
        ("or/", "openrouter"),
        ("codex/", "codex"),
        ("openai/", "openai"),
        ("xai/", "xai"),
        ("zhipu/", "zhipu"),
        ("kimi-code/", "kimi-code"),
        ("minimax/", "minimax"),
        ("moonshot/", "moonshot"),
        ("deepseek/", "deepseek"),
        ("local/", "local"),
        ("nvidia/", "nvidia"),
        ("cloudflare/", "cloudflare"),
    ]
    for prefix, provider in prefix_map:
        if model_lower.startswith(prefix):
            return provider

    name_map = [
        ("claude", "claude"),
        ("gemini", "gemini"),
        ("gpt", "openai"),
        ("grok", "xai"),
        ("glm", "zhipu"),
        ("kimi-for-coding", "kimi-code"),
        ("kimi", "moonshot"),
        ("minimax", "minimax"),
        ("deepseek", "deepseek"),
        ("qwen", "local"),
    ]
    for name, provider in name_map:
        if name in model_lower:
            return provider

    return "claude"


def list_providers() -> list[str]:
    """Return provider names visible in the model catalog."""
    from app.constants.catalog import MODEL_CATALOG

    return sorted({entry.provider for entry in MODEL_CATALOG})


def invalidate(provider: str) -> None:
    """Record provider credential invalidation.

    The old adapter cache is gone. Credential refresh now happens at the
    provider/request boundary, so this remains as a narrow compatibility hook
    for OAuth and preferences endpoints.
    """
    _INVALIDATED_PROVIDERS.add(provider)
    logger.info("Provider credentials invalidated for %s", provider)


def clear_cache() -> None:
    """Compatibility alias for old adapter-cache callers."""
    _INVALIDATED_PROVIDERS.clear()


def _validate_provider(v: str) -> str:
    if v not in set(list_providers()):
        raise ValueError(
            f"Unknown provider: {v!r}. Valid providers: {list_providers()}"
        )
    return v


ValidProvider = Annotated[str, BeforeValidator(_validate_provider)]


__all__ = [
    "ValidProvider",
    "clear_cache",
    "get_provider_for_model",
    "invalidate",
    "list_providers",
]
