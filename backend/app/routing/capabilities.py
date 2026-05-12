"""Provider capability routing.

Extracted from ``app.adapters.registry`` per convergence-map.md C2 — capability
routing is a router concern, not an adapter concern. The adapter factory/cache
stays in ``app.adapters.registry`` (it's slated for deletion in Phase 4 once
the new ``app.llm`` pipeline is the sole code path).
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


_capabilities: dict[str, ProviderCapabilities] = {}


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
