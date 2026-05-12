"""Provider capability routing.

Extracted from ``app.routing.registry`` per convergence-map.md C2 — capability
routing is a router concern, not an adapter concern.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderCapabilities:
    """Declared capabilities for a provider.

    Used for capability-aware routing — no hard-coded ``if provider == "claude"``
    branching in the completion pipeline.
    """

    supports_streaming: bool = True
    supports_tool_execution: bool = False
    supports_thinking: bool = False
    supports_images: bool = False
    supports_cache_retention: bool = False


_capabilities: dict[str, ProviderCapabilities] = {
    "claude": ProviderCapabilities(
        supports_tool_execution=True,
        supports_thinking=True,
        supports_images=True,
        supports_cache_retention=True,
    ),
    "gemini": ProviderCapabilities(
        supports_tool_execution=True,
        supports_thinking=True,
        supports_images=True,
    ),
    "codex": ProviderCapabilities(supports_tool_execution=True),
    "openai": ProviderCapabilities(supports_tool_execution=True, supports_images=True),
    "openrouter": ProviderCapabilities(supports_tool_execution=True, supports_images=True),
    "xai": ProviderCapabilities(supports_tool_execution=True),
    "zhipu": ProviderCapabilities(supports_tool_execution=True),
    "minimax": ProviderCapabilities(supports_tool_execution=True, supports_thinking=True),
    "kimi-code": ProviderCapabilities(supports_tool_execution=True, supports_thinking=True),
    "moonshot": ProviderCapabilities(
        supports_tool_execution=True,
        supports_thinking=True,
        supports_images=True,
    ),
    "deepseek": ProviderCapabilities(supports_tool_execution=True, supports_thinking=True),
    "local": ProviderCapabilities(supports_tool_execution=True, supports_thinking=True),
    "nvidia": ProviderCapabilities(
        supports_tool_execution=True,
        supports_thinking=True,
        supports_images=True,
    ),
    "cloudflare": ProviderCapabilities(supports_tool_execution=True),
}
_DEFAULT_CAPABILITIES = dict(_capabilities)


def set_capabilities(provider: str, capabilities: ProviderCapabilities) -> None:
    """Register declared capabilities for ``provider``."""
    _capabilities[provider] = capabilities


def get_capabilities(provider: str) -> ProviderCapabilities:
    """Get declared capabilities for ``provider``.

    Returns a default (all-False except streaming) ``ProviderCapabilities``
    if the provider has no explicit capabilities registered.
    """
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
    model_value = _model_capability(model, "supports_tool_execution")
    if model_value is not None:
        return model_value
    return get_capabilities(provider).supports_tool_execution


def supports_thinking(provider: str, model: str | None = None) -> bool:
    model_value = _model_capability(model, "has_thinking")
    if model_value is not None:
        return model_value
    return get_capabilities(provider).supports_thinking


def supports_images(provider: str) -> bool:
    return get_capabilities(provider).supports_images


def supports_cache_retention(provider: str) -> bool:
    return get_capabilities(provider).supports_cache_retention


def list_providers_with(capability: str) -> list[str]:
    """Return providers that have ``capability`` enabled.

    ``capability`` is the field name with the ``supports_`` prefix stripped
    (e.g. ``"tool_execution"``, ``"thinking"``).
    """
    attr = f"supports_{capability}"
    if not hasattr(ProviderCapabilities, attr):
        valid = [
            f.name.removeprefix("supports_")
            for f in ProviderCapabilities.__dataclass_fields__.values()
        ]
        raise ValueError(f"Unknown capability: {capability!r}. Valid: {valid}")
    return [name for name, caps in _capabilities.items() if getattr(caps, attr, False)]


def reset() -> None:
    """Reset capability registry. Testing only."""
    _capabilities.clear()
    _capabilities.update(_DEFAULT_CAPABILITIES)


__all__ = [
    "ProviderCapabilities",
    "get_capabilities",
    "list_providers_with",
    "reset",
    "set_capabilities",
    "supports_cache_retention",
    "supports_images",
    "supports_thinking",
    "supports_tools",
]
