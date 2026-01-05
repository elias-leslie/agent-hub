"""Tests for Claude adapter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.base import Message, RateLimitError, AuthenticationError, ProviderError
from app.adapters.claude import ClaudeAdapter


@pytest.fixture
def mock_anthropic():
    """Mock Anthropic client."""
    with patch("app.adapters.claude.anthropic") as mock:
        yield mock


@pytest.fixture
def mock_settings():
    """Mock settings with API key."""
    with patch("app.adapters.claude.settings") as mock:
        mock.anthropic_api_key = "test-api-key"
        yield mock


class TestClaudeAdapter:
    """Tests for ClaudeAdapter."""

    def test_init_with_api_key(self, mock_anthropic, mock_settings):
        """Test initialization with explicit API key."""
        adapter = ClaudeAdapter(api_key="custom-key")
        assert adapter.provider_name == "claude"
        mock_anthropic.AsyncAnthropic.assert_called_with(api_key="custom-key")

    def test_init_from_settings(self, mock_anthropic, mock_settings):
        """Test initialization from settings."""
        adapter = ClaudeAdapter()
        assert adapter.provider_name == "claude"
        mock_anthropic.AsyncAnthropic.assert_called_with(api_key="test-api-key")

    def test_init_no_api_key_raises(self, mock_anthropic, mock_settings):
        """Test that missing API key raises ValueError."""
        mock_settings.anthropic_api_key = ""
        with pytest.raises(ValueError, match="API key not configured"):
            ClaudeAdapter()

    @pytest.mark.asyncio
    async def test_complete_success(self, mock_anthropic, mock_settings):
        """Test successful completion."""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Hello!")]
        mock_response.model = "claude-sonnet-4-5-20250514"
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5
        mock_response.stop_reason = "end_turn"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        adapter = ClaudeAdapter()
        messages = [Message(role="user", content="Hi")]
        result = await adapter.complete(messages, model="claude-sonnet-4-5-20250514")

        assert result.content == "Hello!"
        assert result.model == "claude-sonnet-4-5-20250514"
        assert result.provider == "claude"
        assert result.input_tokens == 10
        assert result.output_tokens == 5
        assert result.finish_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_complete_with_system_message(self, mock_anthropic, mock_settings):
        """Test completion with system message."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Response")]
        mock_response.model = "claude-sonnet-4-5-20250514"
        mock_response.usage.input_tokens = 20
        mock_response.usage.output_tokens = 10
        mock_response.stop_reason = "end_turn"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        adapter = ClaudeAdapter()
        messages = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="Hello"),
        ]
        await adapter.complete(messages, model="claude-sonnet-4-5-20250514")

        # Verify system was passed correctly
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "You are helpful"
        assert len(call_kwargs["messages"]) == 1
        assert call_kwargs["messages"][0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_complete_rate_limit(self, mock_anthropic, mock_settings):
        """Test rate limit handling."""
        import anthropic as real_anthropic

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            side_effect=real_anthropic.RateLimitError(
                message="Rate limited",
                response=MagicMock(status_code=429, headers={"retry-after": "30"}),
                body=None,
            )
        )
        mock_anthropic.AsyncAnthropic.return_value = mock_client
        mock_anthropic.RateLimitError = real_anthropic.RateLimitError
        mock_anthropic.AuthenticationError = real_anthropic.AuthenticationError
        mock_anthropic.APIError = real_anthropic.APIError

        adapter = ClaudeAdapter()
        with pytest.raises(RateLimitError) as exc_info:
            await adapter.complete([Message(role="user", content="Hi")], model="claude-sonnet-4-5-20250514")
        assert exc_info.value.provider == "claude"
        assert exc_info.value.retriable is True

    @pytest.mark.asyncio
    async def test_complete_auth_error(self, mock_anthropic, mock_settings):
        """Test authentication error handling."""
        import anthropic as real_anthropic

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            side_effect=real_anthropic.AuthenticationError(
                message="Invalid API key",
                response=MagicMock(status_code=401),
                body=None,
            )
        )
        mock_anthropic.AsyncAnthropic.return_value = mock_client
        mock_anthropic.RateLimitError = real_anthropic.RateLimitError
        mock_anthropic.AuthenticationError = real_anthropic.AuthenticationError
        mock_anthropic.APIError = real_anthropic.APIError

        adapter = ClaudeAdapter()
        with pytest.raises(AuthenticationError) as exc_info:
            await adapter.complete([Message(role="user", content="Hi")], model="claude-sonnet-4-5-20250514")
        assert exc_info.value.provider == "claude"

    @pytest.mark.asyncio
    async def test_health_check_success(self, mock_anthropic, mock_settings):
        """Test successful health check."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="pong")]
        mock_response.model = "claude-haiku-4-5-20250514"
        mock_response.usage.input_tokens = 1
        mock_response.usage.output_tokens = 1
        mock_response.stop_reason = "end_turn"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        adapter = ClaudeAdapter()
        assert await adapter.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, mock_anthropic, mock_settings):
        """Test failed health check."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("Connection error"))
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        adapter = ClaudeAdapter()
        assert await adapter.health_check() is False
