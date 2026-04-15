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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from pydantic import BeforeValidator

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


@dataclass(frozen=True)
class ProviderCapabilities:
    """Declared capabilities for a provider adapter.

    Used for capability-aware routing — no more hard-coded ``if provider == "claude"``
    branching in the completion pipeline.
    """

    supports_streaming: bool = True
    supports_tool_execution: bool = False
    supports_thinking: bool = False
    supports_images: bool = False
    supports_cache_retention: bool = False


# ---------------------------------------------------------------------------
# Registry internals
# ---------------------------------------------------------------------------

_factories: dict[str, AdapterFactory] = {}
_capabilities: dict[str, ProviderCapabilities] = {}
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
        supports_tool_execution=False, supports_thinking=True,
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
        _capabilities[provider] = capabilities


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
        ("codex/", "codex"),
        ("openai/", "openai"),
        ("xai/", "xai"),
        ("zhipu/", "zhipu"),
        ("minimax/", "minimax"),
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
    ]
    for name, provider in name_map:
        if name in model_lower:
            return provider

    return "claude"  # Default


def list_providers() -> list[str]:
    """Return all registered provider names."""
    _ensure_registered()
    return list(_factories.keys())


# ---------------------------------------------------------------------------
# Capability queries
# ---------------------------------------------------------------------------


def get_capabilities(provider: str) -> ProviderCapabilities:
    """Get declared capabilities for a provider.

    Returns a default (all-False except streaming) ``ProviderCapabilities``
    if the provider has no explicit capabilities registered.
    """
    _ensure_registered()
    return _capabilities.get(provider, ProviderCapabilities())


def _model_capability(model: str | None, attr: str) -> bool | None:
    """Return a model-scoped capability from the catalog, if available."""
    if not model:
        return None
    from app.constants.catalog import get_model_capabilities

    capabilities = get_model_capabilities(model)
    if capabilities is None:
        return None
    return bool(getattr(capabilities, attr, False))


def supports_tools(provider: str, model: str | None = None) -> bool:
    """Return True if the provider/model supports tool execution."""
    model_value = _model_capability(model, "supports_tool_execution")
    if model_value is not None:
        return model_value
    return get_capabilities(provider).supports_tool_execution


def supports_thinking(provider: str, model: str | None = None) -> bool:
    """Return True if the provider/model supports thinking/reasoning mode."""
    model_value = _model_capability(model, "has_thinking")
    if model_value is not None:
        return model_value
    return get_capabilities(provider).supports_thinking


def supports_images(provider: str) -> bool:
    """Return True if the provider supports image inputs."""
    return get_capabilities(provider).supports_images


def supports_cache_retention(provider: str) -> bool:
    """Return True if the provider supports cache retention."""
    return get_capabilities(provider).supports_cache_retention


def list_providers_with(capability: str) -> list[str]:
    """Return providers that have a specific capability enabled.

    Args:
        capability: One of 'streaming', 'tool_execution', 'thinking',
                    'images', 'cache_retention'

    Returns:
        List of provider names with the capability enabled.

    Raises:
        ValueError: If the capability name is invalid.
    """
    _ensure_registered()
    attr = f"supports_{capability}"
    # Validate the capability name
    if not hasattr(ProviderCapabilities, attr):
        valid = [f.name.removeprefix("supports_") for f in ProviderCapabilities.__dataclass_fields__.values()]
        raise ValueError(f"Unknown capability: {capability!r}. Valid: {valid}")
    return [
        name for name, caps in _capabilities.items()
        if getattr(caps, attr, False)
    ]


def reset() -> None:
    """Reset registry state. For testing only."""
    global _initialized
    _factories.clear()
    _capabilities.clear()
    _cache.clear()
    _initialized = False
