"""Provider capability routing.

Extracted from ``app.routing.registry`` per convergence-map.md C2 — capability
routing is a router concern, not an adapter concern.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderCapabilities:
    """Declared provider-level fallbacks when the model catalog has no entry."""

    supports_tool_execution: bool = False
    supports_thinking: bool = False


_capabilities: dict[str, ProviderCapabilities] = {
    "gemini": ProviderCapabilities(supports_tool_execution=True, supports_thinking=True),
    "codex": ProviderCapabilities(supports_tool_execution=True),
    "openai": ProviderCapabilities(supports_tool_execution=True),
    "openrouter": ProviderCapabilities(supports_tool_execution=True),
    "xai": ProviderCapabilities(supports_tool_execution=True),
    "zhipu": ProviderCapabilities(supports_tool_execution=True),
    "minimax": ProviderCapabilities(supports_tool_execution=True, supports_thinking=True),
    "kimi-code": ProviderCapabilities(supports_tool_execution=True, supports_thinking=True),
    "moonshot": ProviderCapabilities(supports_tool_execution=True, supports_thinking=True),
    "deepseek": ProviderCapabilities(supports_tool_execution=True, supports_thinking=True),
    "local": ProviderCapabilities(supports_tool_execution=True, supports_thinking=True),
    "nvidia": ProviderCapabilities(supports_tool_execution=True, supports_thinking=True),
    "cloudflare": ProviderCapabilities(supports_tool_execution=True),
    # The headless Claude Code CLI runs tool-denied; Agent Hub owns the tool loop.
    "claude": ProviderCapabilities(supports_thinking=True),
}


def get_capabilities(provider: str) -> ProviderCapabilities:
    """Get declared capabilities for ``provider`` (all False when unregistered)."""
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


__all__ = [
    "ProviderCapabilities",
    "get_capabilities",
    "supports_thinking",
    "supports_tools",
]
