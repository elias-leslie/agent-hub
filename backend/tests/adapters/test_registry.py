"""Tests for the unified adapter registry."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.adapters import registry


@pytest.fixture(autouse=True)
def _reset_registry():
    """Reset registry state before each test."""
    registry.reset()
    yield
    registry.reset()


def test_all_supported_providers_registered() -> None:
    """Registry should expose the supported provider set only."""
    providers = set(registry.list_providers())
    assert providers == {
        "claude",
        "gemini",
        "codex",
        "openai",
        "openrouter",
        "xai",
        "zhipu",
        "minimax",
        "nvidia",
        "cloudflare",
    }


def test_get_adapter_caches_instances() -> None:
    """Adapters should be cached per provider."""
    a1 = registry.get_adapter("gemini")
    a2 = registry.get_adapter("gemini")
    assert a1 is a2


def test_unknown_provider_raises() -> None:
    """Unknown providers should fail loudly."""
    with pytest.raises(ValueError, match="Unknown provider: nonexistent"):
        registry.get_adapter("nonexistent")


def test_get_provider_for_model_supports_legacy_cloudcode_ids() -> None:
    """Legacy CloudCode IDs should now resolve onto Claude."""
    assert registry.get_provider_for_model("cloudcode/claude-sonnet-4-6") == "claude"
    assert registry.get_provider_for_model("cc/sonnet") == "claude"
    assert registry.get_provider_for_model("gemini-3-flash-preview") == "gemini"


def test_capabilities_reflect_supported_stack() -> None:
    """Capability queries should reflect the supported provider matrix."""
    assert registry.supports_tools("claude") is True
    assert registry.supports_tools("gemini") is True
    assert registry.supports_tools("codex") is True
    assert registry.supports_tools("xai", "xai/grok-4.20-reasoning") is True
    assert registry.supports_tools("xai", "xai/grok-4.20-multi-agent") is False
    assert registry.supports_thinking("gemini") is True
    assert registry.supports_thinking("xai", "xai/grok-4.20-multi-agent") is True
    assert registry.supports_thinking("openai") is False
    assert registry.supports_cache_retention("claude") is True
    assert registry.supports_cache_retention("gemini") is False


def test_list_providers_with_capability() -> None:
    """Capability listings should no longer include removed providers."""
    tool_providers = set(registry.list_providers_with("tool_execution"))
    assert "cloudcode" not in tool_providers
    assert {"claude", "gemini", "codex", "openai"}.issubset(tool_providers)

    thinking_providers = set(registry.list_providers_with("thinking"))
    assert thinking_providers == {"claude", "gemini", "minimax", "nvidia"}


def test_register_custom_provider() -> None:
    """Custom providers can still be registered for tests/extensions."""
    mock = MagicMock()
    mock.provider_name = "custom"
    registry.register("custom", lambda: mock)
    registry._initialized = True

    adapter = registry.get_adapter("custom")
    assert adapter is mock
