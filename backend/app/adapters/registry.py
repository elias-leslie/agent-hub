"""Unified adapter registry — single source of truth for provider→adapter mapping.

Consolidates 4 separate factory sites into one registry with:
- Lazy adapter imports (avoids circular dependencies)
- Global instance cache with per-provider invalidation
- Model→provider resolution via catalog.py
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.adapters.base import ProviderAdapter

logger = logging.getLogger(__name__)

# Type for lazy adapter factory callables
AdapterFactory = Callable[[], "ProviderAdapter"]

# ---------------------------------------------------------------------------
# Registry internals
# ---------------------------------------------------------------------------

_factories: dict[str, AdapterFactory] = {}
_cache: dict[str, ProviderAdapter] = {}
_initialized = False


def _ensure_registered() -> None:
    """Lazily register all adapter factories on first access."""
    global _initialized
    if _initialized:
        return
    _initialized = True

    # Lazy imports to break circular dependencies
    def _claude() -> ProviderAdapter:
        from app.adapters.claude import ClaudeAdapter
        return ClaudeAdapter()

    def _gemini() -> ProviderAdapter:
        from app.adapters.gemini import GeminiAdapter
        return GeminiAdapter()

    def _cloudcode() -> ProviderAdapter:
        from app.adapters.cloudcode_claude import CloudCodeClaudeAdapter
        return CloudCodeClaudeAdapter()

    def _codex() -> ProviderAdapter:
        from app.adapters.codex_oauth import CodexOAuthAdapter
        return CodexOAuthAdapter()

    def _openai() -> ProviderAdapter:
        from app.adapters.openai import OpenAIAdapter
        return OpenAIAdapter()

    def _openrouter() -> ProviderAdapter:
        from app.adapters.openrouter import OpenRouterAdapter
        return OpenRouterAdapter()

    def _xai() -> ProviderAdapter:
        from app.adapters.xai import XAIAdapter
        return XAIAdapter()

    def _zhipu() -> ProviderAdapter:
        from app.adapters.zhipu import ZhipuAdapter
        return ZhipuAdapter()

    def _minimax() -> ProviderAdapter:
        from app.adapters.minimax import MinimaxAdapter
        return MinimaxAdapter()

    register("claude", _claude)
    register("gemini", _gemini)
    register("cloudcode", _cloudcode)
    register("codex", _codex)
    register("openai", _openai)
    register("openrouter", _openrouter)
    register("xai", _xai)
    register("zhipu", _zhipu)
    register("minimax", _minimax)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register(provider: str, factory: AdapterFactory) -> None:
    """Register an adapter factory for a provider.

    Args:
        provider: Provider name (e.g., "claude", "gemini")
        factory: Callable that returns a new ProviderAdapter instance
    """
    _factories[provider] = factory


def get_adapter(provider: str) -> ProviderAdapter:
    """Get a cached adapter instance for a provider.

    Creates the adapter on first access and caches it for reuse.

    Args:
        provider: Provider name

    Returns:
        Cached ProviderAdapter instance

    Raises:
        ValueError: If provider is unknown
    """
    _ensure_registered()

    if provider in _cache:
        return _cache[provider]

    factory = _factories.get(provider)
    if not factory:
        raise ValueError(f"Unknown provider: {provider}")

    adapter = factory()
    _cache[provider] = adapter
    logger.info("Created cached adapter for %s", provider)
    return adapter


def invalidate(provider: str) -> None:
    """Remove a cached adapter so it's recreated with fresh credentials.

    Args:
        provider: Provider name to invalidate
    """
    removed = _cache.pop(provider, None)
    if removed:
        logger.info("Invalidated cached adapter for %s", provider)


def clear_cache() -> None:
    """Clear all cached adapters. Useful for testing."""
    _cache.clear()


def get_provider_for_model(model: str) -> str:
    """Determine provider from model ID using the catalog, with string fallback.

    Checks MODEL_CATALOG_BY_ID first (authoritative), then falls back to
    prefix/name-based detection for models not in the catalog.

    Args:
        model: Model ID or alias (e.g., "claude-sonnet-4-6", "xai/grok-code-fast-1")

    Returns:
        Provider name (e.g., "claude", "gemini", "openai")
    """
    from app.constants.catalog import MODEL_CATALOG_BY_ID, resolve_model

    # Try catalog lookup first (authoritative source)
    resolved = resolve_model(model)
    entry = MODEL_CATALOG_BY_ID.get(resolved)
    if entry:
        return entry.provider

    # Fallback: prefix-based detection
    model_lower = model.lower()
    prefix_map = [
        ("openrouter/", "openrouter"),
        ("or/", "openrouter"),
        ("cloudcode/", "cloudcode"),
        ("codex/", "codex"),
        ("openai/", "openai"),
        ("xai/", "xai"),
        ("zhipu/", "zhipu"),
        ("minimax/", "minimax"),
    ]
    for prefix, provider in prefix_map:
        if model_lower.startswith(prefix):
            return provider

    # Fallback: name-based detection
    name_map = [
        ("claude", "claude"),
        ("gemini", "gemini"),
        ("gpt", "openai"),
        ("grok", "xai"),
        ("glm", "zhipu"),
    ]
    for name, provider in name_map:
        if name in model_lower:
            return provider

    return "claude"  # Default


def list_providers() -> list[str]:
    """Return all registered provider names."""
    _ensure_registered()
    return list(_factories.keys())


def reset() -> None:
    """Reset registry state. For testing only."""
    global _initialized
    _factories.clear()
    _cache.clear()
    _initialized = False
