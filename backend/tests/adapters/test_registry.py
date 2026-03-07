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

    def test_all_providers_registered(self):
        """All 11 providers should have factories registered."""
        providers = [
            "claude", "gemini", "cloudcode", "codex",
            "openai", "openrouter", "xai", "zhipu", "minimax",
            "nvidia", "cloudflare",
        ]
        registry._ensure_registered()
        for provider in providers:
            assert provider in registry._factories, f"{provider} not registered"

    def test_adapter_with_credentials_is_resolvable(self):
        """Providers with available credentials should return adapters."""
        # Claude, Gemini, and CloudCode should work in this environment.
        # Codex requires OAuth credentials that may not be available.
        for provider in ("claude", "gemini", "cloudcode"):
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
        assert registry.get_provider_for_model("cloudflare/flux-2-dev") == "cloudflare"
        assert registry.get_provider_for_model("nvidia/flux.1-dev") == "nvidia"

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
        """Should list all 11 providers."""
        providers = registry.list_providers()
        assert len(providers) == 11
        for expected in ["claude", "gemini", "cloudcode", "codex", "openai", "openrouter", "xai", "zhipu", "minimax", "nvidia", "cloudflare"]:
            assert expected in providers


class TestCapabilities:
    """Tests for capability queries."""

    def test_claude_supports_all(self):
        """Claude should support tools, thinking, images, cache retention."""
        caps = registry.get_capabilities("claude")
        assert caps.supports_tool_execution is True
        assert caps.supports_thinking is True
        assert caps.supports_images is True
        assert caps.supports_cache_retention is True
        assert caps.supports_streaming is True

    def test_codex_provider_is_conservative_without_model_context(self):
        """Provider-level Codex defaults stay conservative without a model hint."""
        caps = registry.get_capabilities("codex")
        assert caps.supports_tool_execution is False
        assert caps.supports_thinking is False
        assert caps.supports_images is False
        assert caps.supports_cache_retention is False
        assert caps.supports_streaming is True  # streaming is default True

    def test_codex_model_capabilities_come_from_catalog(self):
        """Model-aware capability checks should use the model catalog."""
        assert registry.supports_thinking("codex", "codex/gpt-5.4") is True
        assert registry.supports_tools("codex", "codex/gpt-5.4") is True
        assert registry.supports_tools("codex", "codex/gpt-5.1-codex-mini") is False

    def test_gemini_supports_tools_and_thinking(self):
        """Gemini should support tools, thinking, images but not cache retention."""
        caps = registry.get_capabilities("gemini")
        assert caps.supports_tool_execution is True
        assert caps.supports_thinking is True
        assert caps.supports_images is True
        assert caps.supports_cache_retention is False

    def test_openai_compat_supports_tools(self):
        """OpenAI-compat providers should support tool execution."""
        for provider in ("openai", "openrouter", "xai", "zhipu", "nvidia", "cloudflare"):
            assert registry.supports_tools(provider), f"{provider} should support tools"

    def test_supports_tools_query(self):
        """supports_tools() should return correct results."""
        assert registry.supports_tools("claude") is True
        assert registry.supports_tools("gemini") is True
        assert registry.supports_tools("codex") is False
        assert registry.supports_tools("codex", "codex/gpt-5.4") is True

    def test_supports_thinking_query(self):
        """supports_thinking() should return correct results."""
        assert registry.supports_thinking("claude") is True
        assert registry.supports_thinking("gemini") is True
        assert registry.supports_thinking("cloudcode") is True
        assert registry.supports_thinking("openai") is False
        assert registry.supports_thinking("codex", "codex/gpt-5.1-codex-mini") is False

    def test_supports_cache_retention_query(self):
        """Only Claude should support cache retention."""
        assert registry.supports_cache_retention("claude") is True
        assert registry.supports_cache_retention("gemini") is False
        assert registry.supports_cache_retention("openai") is False

    def test_list_providers_with_tool_execution(self):
        """Should list all tool-capable providers."""
        tool_providers = registry.list_providers_with("tool_execution")
        assert "claude" in tool_providers
        assert "gemini" in tool_providers
        assert "openai" in tool_providers
        assert "codex" not in tool_providers
        assert len(tool_providers) == 9  # all except codex and minimax

    def test_list_providers_with_thinking(self):
        """Should list thinking-capable providers."""
        thinking_providers = registry.list_providers_with("thinking")
        assert set(thinking_providers) == {"claude", "gemini", "cloudcode", "minimax", "nvidia"}

    def test_list_providers_with_invalid_capability(self):
        """Invalid capability should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown capability"):
            registry.list_providers_with("teleportation")

    def test_unknown_provider_returns_defaults(self):
        """Unknown provider should return default capabilities."""
        caps = registry.get_capabilities("nonexistent")
        assert caps.supports_tool_execution is False
        assert caps.supports_streaming is True

    def test_register_with_capabilities(self):
        """Custom providers can register with capabilities."""
        mock = MagicMock()
        registry._initialized = True
        registry.register(
            "custom", lambda: mock,
            registry.ProviderCapabilities(supports_tool_execution=True, supports_thinking=True),
        )
        assert registry.supports_tools("custom") is True
        assert registry.supports_thinking("custom") is True
        assert registry.supports_images("custom") is False


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
