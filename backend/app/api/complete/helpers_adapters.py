"""Adapter factory and cache for completion API."""

from __future__ import annotations

import logging

from app.adapters.base import ProviderAdapter
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter
from app.adapters.openai import OpenAIAdapter
from app.adapters.openrouter import OpenRouterAdapter
from app.adapters.xai import XAIAdapter
from app.adapters.zhipu import ZhipuAdapter

logger = logging.getLogger(__name__)

# Cached adapter instances - created once, reused across requests
_adapter_cache: dict[str, ProviderAdapter] = {}

_ADAPTER_FACTORIES: dict[str, type[ProviderAdapter]] = {
    "claude": ClaudeAdapter,
    "gemini": GeminiAdapter,
    "openai": OpenAIAdapter,
    "openrouter": OpenRouterAdapter,
    "xai": XAIAdapter,
    "zhipu": ZhipuAdapter,
}


def get_adapter(provider: str) -> ProviderAdapter:
    """Get cached adapter instance for provider."""
    if provider in _adapter_cache:
        return _adapter_cache[provider]
    factory = _ADAPTER_FACTORIES.get(provider)
    if not factory:
        raise ValueError(f"Unknown provider: {provider}")
    adapter = factory()
    _adapter_cache[provider] = adapter
    logger.info(f"Created cached adapter for {provider}")
    return adapter


def clear_adapter_cache() -> None:
    """Clear the adapter cache. Useful for testing."""
    _adapter_cache.clear()
