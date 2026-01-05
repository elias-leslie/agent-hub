"""Tests for ModelRouter."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.adapters.base import (
    CompletionResult,
    Message,
    ProviderError,
    RateLimitError,
)
from app.services.router import ModelRouter


@pytest.fixture
def mock_claude_adapter():
    """Create mock Claude adapter."""
    adapter = MagicMock()
    adapter.complete = AsyncMock(
        return_value=CompletionResult(
            content="Hello from Claude!",
            model="claude-sonnet-4-5-20250514",
            provider="claude",
            input_tokens=10,
            output_tokens=5,
            finish_reason="end_turn",
        )
    )
    return adapter


@pytest.fixture
def mock_gemini_adapter():
    """Create mock Gemini adapter."""
    adapter = MagicMock()
    adapter.complete = AsyncMock(
        return_value=CompletionResult(
            content="Hello from Gemini!",
            model="gemini-2.0-flash",
            provider="gemini",
            input_tokens=8,
            output_tokens=4,
            finish_reason="STOP",
        )
    )
    return adapter


class TestModelRouter:
    """Tests for ModelRouter."""

    def test_init_default_chain(self):
        """Test default provider chain."""
        router = ModelRouter()
        assert router._provider_chain == ["claude", "gemini"]

    def test_init_custom_chain(self):
        """Test custom provider chain."""
        router = ModelRouter(provider_chain=["gemini", "claude"])
        assert router._provider_chain == ["gemini", "claude"]

    def test_determine_primary_provider_claude(self):
        """Test primary provider detection for Claude model."""
        router = ModelRouter()
        assert router._determine_primary_provider("claude-sonnet-4-5-20250514") == "claude"

    def test_determine_primary_provider_gemini(self):
        """Test primary provider detection for Gemini model."""
        router = ModelRouter()
        assert router._determine_primary_provider("gemini-2.0-flash") == "gemini"

    def test_determine_primary_provider_unknown(self):
        """Test primary provider detection for unknown model."""
        router = ModelRouter()
        # Defaults to first in chain
        assert router._determine_primary_provider("unknown-model") == "claude"

    @pytest.mark.asyncio
    async def test_complete_primary_success(self, mock_claude_adapter, mock_gemini_adapter):
        """Test successful completion with primary provider."""
        router = ModelRouter(
            adapter_factory={
                "claude": lambda: mock_claude_adapter,
                "gemini": lambda: mock_gemini_adapter,
            }
        )

        messages = [Message(role="user", content="Hi")]
        result = await router.complete(messages, model="claude-sonnet-4-5-20250514")

        assert result.content == "Hello from Claude!"
        assert result.provider == "claude"
        mock_claude_adapter.complete.assert_called_once()
        mock_gemini_adapter.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_on_error(self, mock_claude_adapter, mock_gemini_adapter):
        """Test fallback when primary provider fails with rate limit."""
        # Make Claude fail with rate limit
        mock_claude_adapter.complete = AsyncMock(side_effect=RateLimitError("claude"))

        router = ModelRouter(
            adapter_factory={
                "claude": lambda: mock_claude_adapter,
                "gemini": lambda: mock_gemini_adapter,
            }
        )

        messages = [Message(role="user", content="Hi")]
        result = await router.complete(messages, model="claude-sonnet-4-5-20250514")

        # Should fall back to Gemini
        assert result.content == "Hello from Gemini!"
        assert result.provider == "gemini"
        mock_claude_adapter.complete.assert_called_once()
        mock_gemini_adapter.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_on_retriable_error(self, mock_claude_adapter, mock_gemini_adapter):
        """Test fallback on retriable provider error."""
        mock_claude_adapter.complete = AsyncMock(
            side_effect=ProviderError("Server error", provider="claude", retriable=True)
        )

        router = ModelRouter(
            adapter_factory={
                "claude": lambda: mock_claude_adapter,
                "gemini": lambda: mock_gemini_adapter,
            }
        )

        messages = [Message(role="user", content="Hi")]
        result = await router.complete(messages, model="claude-sonnet-4-5-20250514")

        assert result.provider == "gemini"

    @pytest.mark.asyncio
    async def test_no_fallback_on_non_retriable_error(self, mock_claude_adapter, mock_gemini_adapter):
        """Test that non-retriable errors don't trigger fallback."""
        mock_claude_adapter.complete = AsyncMock(
            side_effect=ProviderError("Auth error", provider="claude", retriable=False)
        )

        router = ModelRouter(
            adapter_factory={
                "claude": lambda: mock_claude_adapter,
                "gemini": lambda: mock_gemini_adapter,
            }
        )

        messages = [Message(role="user", content="Hi")]
        with pytest.raises(ProviderError) as exc_info:
            await router.complete(messages, model="claude-sonnet-4-5-20250514")

        assert exc_info.value.provider == "claude"
        mock_gemini_adapter.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_providers_fail(self, mock_claude_adapter, mock_gemini_adapter):
        """Test error when all providers fail."""
        mock_claude_adapter.complete = AsyncMock(side_effect=RateLimitError("claude"))
        mock_gemini_adapter.complete = AsyncMock(side_effect=RateLimitError("gemini"))

        router = ModelRouter(
            adapter_factory={
                "claude": lambda: mock_claude_adapter,
                "gemini": lambda: mock_gemini_adapter,
            }
        )

        messages = [Message(role="user", content="Hi")]
        with pytest.raises(RateLimitError):
            await router.complete(messages, model="claude-sonnet-4-5-20250514")

    @pytest.mark.asyncio
    async def test_model_mapping_on_fallback(self, mock_claude_adapter, mock_gemini_adapter):
        """Test that model is mapped when falling back."""
        mock_claude_adapter.complete = AsyncMock(side_effect=RateLimitError("claude"))

        router = ModelRouter(
            adapter_factory={
                "claude": lambda: mock_claude_adapter,
                "gemini": lambda: mock_gemini_adapter,
            }
        )

        messages = [Message(role="user", content="Hi")]
        await router.complete(messages, model="claude-sonnet-4-5-20250514")

        # Verify Gemini was called with mapped model
        call_kwargs = mock_gemini_adapter.complete.call_args.kwargs
        assert "gemini" in call_kwargs["model"].lower()

    @pytest.mark.asyncio
    async def test_config_error_fallback(self, mock_claude_adapter, mock_gemini_adapter):
        """Test fallback when primary has config error (missing API key)."""
        # Claude factory raises ValueError (missing API key)
        def claude_factory():
            raise ValueError("API key not configured")

        router = ModelRouter(
            adapter_factory={
                "claude": claude_factory,
                "gemini": lambda: mock_gemini_adapter,
            }
        )

        messages = [Message(role="user", content="Hi")]
        result = await router.complete(messages, model="claude-sonnet-4-5-20250514")

        # Should fall back to Gemini
        assert result.provider == "gemini"
