"""Unified adapter registry — single source of truth for provider→adapter mapping.

Consolidates 4 separate factory sites into one registry with:
- Lazy adapter imports (avoids circular dependencies)
- Global instance cache with per-provider invalidation
- Model→provider resolution via catalog.py
- Capability-aware routing (supports_tools, supports_thinking, etc.)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Annotated

from pydantic import BeforeValidator

# Capability routing moved to app.routing.capabilities per convergence-map.md C2.
# Re-exported with adapter-aware wrappers that trigger lazy factory registration.
# Phase 4: callers import from app.routing.capabilities directly.
from app.routing import capabilities as _caps
from app.routing.capabilities import (
    ProviderCapabilities,
)
from app.routing.capabilities import reset as _reset_capabilities
from app.routing.capabilities import (
    set_capabilities as _set_capabilities,
)


def get_capabilities(provider: str) -> ProviderCapabilities:
    _ensure_registered()
    return _caps.get_capabilities(provider)


def supports_tools(provider: str, model: str | None = None) -> bool:
    _ensure_registered()
    return _caps.supports_tools(provider, model)


def supports_thinking(provider: str, model: str | None = None) -> bool:
    _ensure_registered()
    return _caps.supports_thinking(provider, model)


def list_providers_with(capability: str) -> list[str]:
    _ensure_registered()
    return _caps.list_providers_with(capability)


def supports_cache_retention(provider: str) -> bool:
    _ensure_registered()
    return _caps.supports_cache_retention(provider)


def supports_images(provider: str) -> bool:
    _ensure_registered()
    return _caps.supports_images(provider)

if TYPE_CHECKING:
    from app.adapters.base import ProviderAdapter


def _validate_provider(v: str) -> str:
    """Validate that a provider name is registered in the adapter registry."""
    _ensure_registered()
    if v not in _factories:
        raise ValueError(
            f"Unknown provider: {v!r}. Valid providers: {list(_factories.keys())}"
        )
    return v


ValidProvider = Annotated[str, BeforeValidator(_validate_provider)]
"""Provider name validated against the adapter registry at runtime.

Use this type in Pydantic models and dataclasses instead of
``Literal["claude", "gemini"]`` so that new providers are accepted
automatically when registered."""

logger = logging.getLogger(__name__)

# Type for lazy adapter factory callables
AdapterFactory = Callable[[], "ProviderAdapter"]


# ---------------------------------------------------------------------------
# Registry internals
# ---------------------------------------------------------------------------

_factories: dict[str, AdapterFactory] = {}
_cache: dict[str, ProviderAdapter] = {}
_initialized: bool = False


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

    def _kimi_code() -> ProviderAdapter:
        from app.adapters.kimi_code import KimiCodeAdapter
        return KimiCodeAdapter()

    def _moonshot() -> ProviderAdapter:
        from app.adapters.moonshot import MoonshotAdapter
        return MoonshotAdapter()

    def _deepseek() -> ProviderAdapter:
        from app.adapters.deepseek import DeepSeekAdapter
        return DeepSeekAdapter()

    def _local() -> ProviderAdapter:
        from app.adapters.local import LocalAdapter
        return LocalAdapter()

    def _nvidia() -> ProviderAdapter:
        from app.adapters.nvidia import NvidiaAdapter
        return NvidiaAdapter()

    def _cloudflare() -> ProviderAdapter:
        from app.adapters.cloudflare import CloudflareAdapter
        return CloudflareAdapter()

    register("claude", _claude, ProviderCapabilities(
        supports_tool_execution=True, supports_thinking=True,
        supports_images=True, supports_cache_retention=True,
    ))
    register("gemini", _gemini, ProviderCapabilities(
        supports_tool_execution=True, supports_thinking=True,
        supports_images=True,
    ))
    register("codex", _codex, ProviderCapabilities(
        supports_tool_execution=True,
    ))
    register("openai", _openai, ProviderCapabilities(
        supports_tool_execution=True, supports_images=True,
    ))
    register("openrouter", _openrouter, ProviderCapabilities(
        supports_tool_execution=True, supports_images=True,
    ))
    register("xai", _xai, ProviderCapabilities(
        supports_tool_execution=True,
    ))
    register("zhipu", _zhipu, ProviderCapabilities(
        supports_tool_execution=True,
    ))
    register("minimax", _minimax, ProviderCapabilities(
        supports_tool_execution=True, supports_thinking=True,
    ))
    register("kimi-code", _kimi_code, ProviderCapabilities(
        supports_tool_execution=True, supports_thinking=True,
    ))
    register("moonshot", _moonshot, ProviderCapabilities(
        supports_tool_execution=True, supports_thinking=True,
        supports_images=True,
    ))
    register("deepseek", _deepseek, ProviderCapabilities(
        supports_tool_execution=True, supports_thinking=True,
    ))
    register("local", _local, ProviderCapabilities(
        supports_tool_execution=True, supports_thinking=True,
    ))
    register("nvidia", _nvidia, ProviderCapabilities(
        supports_tool_execution=True, supports_thinking=True,
        supports_images=True,
    ))
    register("cloudflare", _cloudflare, ProviderCapabilities(
        supports_tool_execution=True,
    ))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register(
    provider: str,
    factory: AdapterFactory,
    capabilities: ProviderCapabilities | None = None,
) -> None:
    """Register an adapter factory for a provider.

    Args:
        provider: Provider name (e.g., "claude", "gemini")
        factory: Callable that returns a new ProviderAdapter instance
        capabilities: Declared capabilities for the provider
    """
    _factories[provider] = factory
    if capabilities is not None:
        _set_capabilities(provider, capabilities)


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
        model: Model ID or alias (e.g., "claude-sonnet-4-6", "xai/grok-4.3")

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

    # Fallback: name-based detection
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

    return "claude"  # Default


def list_providers() -> list[str]:
    """Return all registered provider names."""
    _ensure_registered()
    return list(_factories.keys())


def reset() -> None:
    """Reset registry state. For testing only."""
    global _initialized
    _factories.clear()
    _reset_capabilities()
    _cache.clear()
    _initialized = False
