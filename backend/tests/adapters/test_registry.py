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


class TestGetAdapter:
    """Tests for get_adapter()."""

    def test_all_nine_providers_registered(self):
        """All 9 providers should have factories registered."""
        providers = [
            "claude", "gemini", "cloudcode", "codex",
            "openai", "openrouter", "xai", "zhipu", "minimax",
        ]
        registry._ensure_registered()
        for provider in providers:
            assert provider in registry._factories, f"{provider} not registered"

    def test_adapter_with_credentials_is_resolvable(self):
        """Providers with available credentials should return adapters."""
        # Claude and Gemini should work in this environment
        for provider in ("claude", "gemini", "cloudcode", "codex"):
            adapter = registry.get_adapter(provider)
            assert adapter is not None
            assert hasattr(adapter, "provider_name")

    def test_unknown_provider_raises(self):
        """Unknown provider should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown provider: nonexistent"):
            registry.get_adapter("nonexistent")

    def test_adapter_is_cached(self):
        """Same provider should return the same cached instance."""
        a1 = registry.get_adapter("gemini")
        a2 = registry.get_adapter("gemini")
        assert a1 is a2

    def test_different_providers_return_different_instances(self):
        """Different providers should return different adapter instances."""
        claude = registry.get_adapter("claude")
        gemini = registry.get_adapter("gemini")
        assert claude is not gemini


class TestInvalidate:
    """Tests for invalidate()."""

    def test_invalidate_clears_cached_adapter(self):
        """After invalidation, a new adapter instance is created."""
        a1 = registry.get_adapter("gemini")
        registry.invalidate("gemini")
        a2 = registry.get_adapter("gemini")
        assert a1 is not a2

    def test_invalidate_nonexistent_is_noop(self):
        """Invalidating a provider not in cache should not raise."""
        registry.invalidate("nonexistent")  # Should not raise


class TestClearCache:
    """Tests for clear_cache()."""

    def test_clear_cache_removes_all(self):
        """Clearing cache should force re-creation of all adapters."""
        a1 = registry.get_adapter("gemini")
        registry.clear_cache()
        a2 = registry.get_adapter("gemini")
        assert a1 is not a2


class TestGetProviderForModel:
    """Tests for get_provider_for_model()."""

    def test_catalog_models(self):
        """Models in the catalog should resolve via catalog lookup."""
        from app.constants.models import CLAUDE_SONNET, GEMINI_FLASH

        assert registry.get_provider_for_model(CLAUDE_SONNET) == "claude"
        assert registry.get_provider_for_model(GEMINI_FLASH) == "gemini"

    def test_alias_resolution(self):
        """Model aliases should resolve correctly."""
        assert registry.get_provider_for_model("sonnet") == "claude"
        assert registry.get_provider_for_model("flash") == "gemini"
        assert registry.get_provider_for_model("opus") == "claude"

    def test_prefix_based_detection(self):
        """Prefix-based model names should resolve correctly."""
        assert registry.get_provider_for_model("openrouter/some-model") == "openrouter"
        assert registry.get_provider_for_model("or/some-model") == "openrouter"
        assert registry.get_provider_for_model("cloudcode/model") == "cloudcode"
        assert registry.get_provider_for_model("xai/grok-fast") == "xai"
        assert registry.get_provider_for_model("zhipu/glm") == "zhipu"
        assert registry.get_provider_for_model("minimax/m1") == "minimax"

    def test_name_based_detection(self):
        """Name-based model names should resolve correctly."""
        assert registry.get_provider_for_model("claude-sonnet-4-5") == "claude"
        assert registry.get_provider_for_model("gemini-3-flash") == "gemini"
        assert registry.get_provider_for_model("gpt-5") == "openai"
        assert registry.get_provider_for_model("grok-3") == "xai"
        assert registry.get_provider_for_model("glm-4") == "zhipu"

    def test_unknown_model_defaults_to_claude(self):
        """Unknown model names should default to 'claude'."""
        assert registry.get_provider_for_model("unknown-model") == "claude"


class TestListProviders:
    """Tests for list_providers()."""

    def test_lists_all_registered(self):
        """Should list all 9 providers."""
        providers = registry.list_providers()
        assert len(providers) == 9
        for expected in ["claude", "gemini", "cloudcode", "codex", "openai", "openrouter", "xai", "zhipu", "minimax"]:
            assert expected in providers


class TestCustomRegistration:
    """Tests for register()."""

    def test_register_custom_provider(self):
        """Custom providers can be registered."""
        mock = MagicMock()
        mock.provider_name = "custom"
        registry.register("custom", lambda: mock)

        # Need to mark as initialized to avoid re-registration
        registry._initialized = True

        adapter = registry.get_adapter("custom")
        assert adapter is mock
