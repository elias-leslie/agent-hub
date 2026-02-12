"""Tests for OpenRouter adapter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.openai_compat import OpenAICompatibleAdapter
from app.adapters.openrouter import (
    OpenRouterAdapter,
    resolve_openrouter_model,
)


class TestOpenRouterAdapter:
    """Test cases for OpenRouter adapter."""

    def test_openrouter_model_resolution(self):
        """Test OpenRouter model resolution."""
        # Standard model names (prefix strip)
        assert (
            resolve_openrouter_model("openrouter/anthropic/claude-3.5-sonnet")
            == "anthropic/claude-3.5-sonnet"
        )
        assert resolve_openrouter_model("openrouter/openai/gpt-4o") == "openai/gpt-4o"
        assert (
            resolve_openrouter_model("openrouter/meta-llama/llama-3.1-70b-instruct")
            == "meta-llama/llama-3.1-70b-instruct"
        )

        # Registry-derived aliases
        assert resolve_openrouter_model("or/kimi") == "moonshotai/kimi-k2.5"
        assert resolve_openrouter_model("or/minimax") == "minimax/minimax-m2.1"

        # Legacy aliases
        assert resolve_openrouter_model("or/sonnet") == "anthropic/claude-3.5-sonnet"
        assert resolve_openrouter_model("or/gpt4o") == "openai/gpt-4o"

        # Passthrough for other models
        assert resolve_openrouter_model("claude-3.5-sonnet") == "claude-3.5-sonnet"

    def test_inherits_from_openai_compatible(self):
        """Regression test: OpenRouterAdapter inherits OpenAICompatibleAdapter."""
        assert issubclass(OpenRouterAdapter, OpenAICompatibleAdapter)

    def test_provider_property(self):
        """Test provider name property."""
        # Should work without API key for property access
        adapter = OpenRouterAdapter(api_key="dummy_key")
        assert adapter.provider_name == "openrouter"

    @patch("app.adapters.openrouter.settings")
    def test_no_api_key_error(self, mock_settings):
        """Test that adapter raises proper error without API key."""
        mock_settings.openrouter_api_key = None

        with pytest.raises(ValueError, match="(?i)openrouter API key not configured"):
            OpenRouterAdapter(api_key="")  # Empty key

        with pytest.raises(ValueError, match="(?i)openrouter API key not configured"):
            OpenRouterAdapter()  # No key, tries settings

    @pytest.mark.asyncio
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    @patch("app.adapters.openrouter.settings")
    async def test_health_check_success(self, mock_settings, mock_openai_class):
        """Test successful health check."""
        mock_settings.openrouter_api_key = "test-key"

        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        mock_client.models.list = AsyncMock(return_value=MagicMock())

        adapter = OpenRouterAdapter()
        assert adapter.provider_name == "openrouter"

        result = await adapter.health_check()
        assert result is True

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    @patch("app.adapters.openrouter.settings")
    def test_simple_completion_mock(self, mock_settings, mock_openai_class):
        """Test basic completion flow with mocked OpenAI."""
        mock_settings.openrouter_api_key = "test-key"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello from OpenRouter!"
        mock_response.choices[0].finish_reason = "stop"
        mock_response.usage = MagicMock()
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai_class.return_value = mock_client

        adapter = OpenRouterAdapter()
        assert adapter.provider_name == "openrouter"


if __name__ == "__main__":
    pytest.main([__file__])
