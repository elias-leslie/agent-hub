"""Tests for Gemini adapter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.base import Message, RateLimitError, AuthenticationError, ProviderError
from app.adapters.gemini import GeminiAdapter


@pytest.fixture
def mock_genai():
    """Mock Google GenAI client."""
    with patch("app.adapters.gemini.genai") as mock:
        yield mock


@pytest.fixture
def mock_settings():
    """Mock settings with API key."""
    with patch("app.adapters.gemini.settings") as mock:
        mock.gemini_api_key = "test-api-key"
        yield mock


class TestGeminiAdapter:
    """Tests for GeminiAdapter."""

    def test_init_with_api_key(self, mock_genai, mock_settings):
        """Test initialization with explicit API key."""
        adapter = GeminiAdapter(api_key="custom-key")
        assert adapter.provider_name == "gemini"
        mock_genai.Client.assert_called_with(api_key="custom-key")

    def test_init_from_settings(self, mock_genai, mock_settings):
        """Test initialization from settings."""
        adapter = GeminiAdapter()
        assert adapter.provider_name == "gemini"
        mock_genai.Client.assert_called_with(api_key="test-api-key")

    def test_init_no_api_key_raises(self, mock_genai, mock_settings):
        """Test that missing API key raises ValueError."""
        mock_settings.gemini_api_key = ""
        with pytest.raises(ValueError, match="API key not configured"):
            GeminiAdapter()

    @pytest.mark.asyncio
    async def test_complete_success(self, mock_genai, mock_settings):
        """Test successful completion."""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.text = "Hello!"
        mock_response.usage_metadata = MagicMock()
        mock_response.usage_metadata.prompt_token_count = 10
        mock_response.usage_metadata.candidates_token_count = 5
        mock_response.candidates = [MagicMock(finish_reason="STOP")]

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
        mock_genai.Client.return_value = mock_client

        adapter = GeminiAdapter()
        messages = [Message(role="user", content="Hi")]
        result = await adapter.complete(messages, model="gemini-2.0-flash")

        assert result.content == "Hello!"
        assert result.model == "gemini-2.0-flash"
        assert result.provider == "gemini"
        assert result.input_tokens == 10
        assert result.output_tokens == 5

    @pytest.mark.asyncio
    async def test_complete_with_system_message(self, mock_genai, mock_settings):
        """Test completion with system message."""
        mock_response = MagicMock()
        mock_response.text = "Response"
        mock_response.usage_metadata = MagicMock()
        mock_response.usage_metadata.prompt_token_count = 20
        mock_response.usage_metadata.candidates_token_count = 10
        mock_response.candidates = [MagicMock(finish_reason="STOP")]

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
        mock_genai.Client.return_value = mock_client

        adapter = GeminiAdapter()
        messages = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="Hello"),
        ]
        await adapter.complete(messages, model="gemini-2.0-flash")

        # Verify call was made
        mock_client.aio.models.generate_content.assert_called_once()
        call_kwargs = mock_client.aio.models.generate_content.call_args.kwargs
        # System instruction should be in config
        assert call_kwargs["config"].system_instruction == "You are helpful"

    @pytest.mark.asyncio
    async def test_complete_rate_limit(self, mock_genai, mock_settings):
        """Test rate limit handling."""
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("429 Too Many Requests")
        )
        mock_genai.Client.return_value = mock_client

        adapter = GeminiAdapter()
        with pytest.raises(RateLimitError) as exc_info:
            await adapter.complete([Message(role="user", content="Hi")], model="gemini-2.0-flash")
        assert exc_info.value.provider == "gemini"
        assert exc_info.value.retriable is True

    @pytest.mark.asyncio
    async def test_complete_auth_error(self, mock_genai, mock_settings):
        """Test authentication error handling."""
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("401 Invalid API key")
        )
        mock_genai.Client.return_value = mock_client

        adapter = GeminiAdapter()
        with pytest.raises(AuthenticationError) as exc_info:
            await adapter.complete([Message(role="user", content="Hi")], model="gemini-2.0-flash")
        assert exc_info.value.provider == "gemini"

    @pytest.mark.asyncio
    async def test_complete_quota_error(self, mock_genai, mock_settings):
        """Test quota exceeded handling."""
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("quota exceeded for this project")
        )
        mock_genai.Client.return_value = mock_client

        adapter = GeminiAdapter()
        with pytest.raises(RateLimitError) as exc_info:
            await adapter.complete([Message(role="user", content="Hi")], model="gemini-2.0-flash")
        assert exc_info.value.provider == "gemini"

    @pytest.mark.asyncio
    async def test_health_check_success(self, mock_genai, mock_settings):
        """Test successful health check."""
        mock_response = MagicMock()
        mock_response.text = "pong"

        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
        mock_genai.Client.return_value = mock_client

        adapter = GeminiAdapter()
        assert await adapter.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, mock_genai, mock_settings):
        """Test failed health check."""
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(side_effect=Exception("Connection error"))
        mock_genai.Client.return_value = mock_client

        adapter = GeminiAdapter()
        assert await adapter.health_check() is False
