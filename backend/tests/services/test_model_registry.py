"""Tests for ModelRegistry service."""

import pytest

from app.services.model_registry import ModelRegistry, get_model_registry


@pytest.fixture
def registry():
    """Fresh registry instance for each test."""
    ModelRegistry.reset_instance()
    return ModelRegistry.get_instance()


class TestModelRegistry:
    """Tests for ModelRegistry."""

    def test_singleton_pattern(self):
        """Get instance returns same instance."""
        ModelRegistry.reset_instance()
        r1 = ModelRegistry.get_instance()
        r2 = ModelRegistry.get_instance()
        assert r1 is r2

    def test_loads_defaults(self, registry: ModelRegistry):
        """Registry loads default models."""
        models = registry.list_all()
        assert len(models) >= 6  # At least 3 Claude + 3 Gemini

    def test_get_model(self, registry: ModelRegistry):
        """Get specific model by ID."""
        model = registry.get("claude-sonnet-4-5")
        assert model is not None
        assert model.id == "claude-sonnet-4-5"
        assert model.provider == "anthropic"
        assert model.context_window == 200000

    def test_get_nonexistent_model(self, registry: ModelRegistry):
        """Get nonexistent model returns None."""
        model = registry.get("nonexistent-model")
        assert model is None

    def test_list_by_provider(self, registry: ModelRegistry):
        """Filter models by provider."""
        anthropic_models = registry.list_by_provider("anthropic")
        assert len(anthropic_models) >= 3
        for m in anthropic_models:
            assert m.provider == "anthropic"

        google_models = registry.list_by_provider("google")
        assert len(google_models) >= 3
        for m in google_models:
            assert m.provider == "google"

    def test_list_active(self, registry: ModelRegistry):
        """List only active models."""
        active = registry.list_active()
        assert len(active) > 0
        for m in active:
            assert m.is_active is True

    def test_get_context_window(self, registry: ModelRegistry):
        """Get context window for known model."""
        ctx = registry.get_context_window("claude-sonnet-4-5")
        assert ctx == 200000

        ctx = registry.get_context_window("gemini-3-flash-preview")
        assert ctx == 1000000

    def test_get_context_window_unknown_model(self, registry: ModelRegistry):
        """Get context window with pattern matching fallback."""
        # Unknown Claude model gets Claude default
        ctx = registry.get_context_window("claude-future-model")
        assert ctx == 200000

        # Unknown Gemini model gets Gemini default
        ctx = registry.get_context_window("gemini-future-model")
        assert ctx == 1000000

        # Completely unknown gets conservative default
        ctx = registry.get_context_window("unknown-model")
        assert ctx == 128000

    def test_get_max_output_tokens(self, registry: ModelRegistry):
        """Get max output tokens for known model."""
        max_out = registry.get_max_output_tokens("claude-sonnet-4-5")
        assert max_out == 64000

    def test_model_has_capability(self, registry: ModelRegistry):
        """Check model capabilities."""
        model = registry.get("claude-sonnet-4-5")
        assert model is not None
        assert model.has_capability("vision") is True
        assert model.has_capability("function_calling") is True
        assert model.has_capability("nonexistent") is False

    def test_image_model_has_image_gen(self, registry: ModelRegistry):
        """Image model has image_gen capability."""
        model = registry.get("gemini-3-pro-image-preview")
        assert model is not None
        assert model.has_capability("image_gen") is True


class TestGetModelRegistry:
    """Tests for get_model_registry helper."""

    def test_returns_registry(self):
        """Helper returns registry instance."""
        ModelRegistry.reset_instance()
        registry = get_model_registry()
        assert isinstance(registry, ModelRegistry)
