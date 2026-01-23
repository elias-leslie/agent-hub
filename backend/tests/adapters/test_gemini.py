"""Tests for Gemini adapter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.base import AuthenticationError, Message, RateLimitError
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
        # Check that Client was called with api_key and http_options
        call_kwargs = mock_genai.Client.call_args.kwargs
        assert call_kwargs["api_key"] == "custom-key"
        assert "http_options" in call_kwargs

    def test_init_from_settings(self, mock_genai, mock_settings):
        """Test initialization from settings."""
        adapter = GeminiAdapter()
        assert adapter.provider_name == "gemini"
        # Check that Client was called with api_key and http_options
        call_kwargs = mock_genai.Client.call_args.kwargs
        assert call_kwargs["api_key"] == "test-api-key"
        assert "http_options" in call_kwargs

    def test_init_with_sdk_timeout(self, mock_genai, mock_settings):
        """Test that SDK timeout is configured to 90 seconds."""
        adapter = GeminiAdapter()
        # Check that Client was called with http_options containing timeout=90
        call_kwargs = mock_genai.Client.call_args.kwargs
        http_options = call_kwargs["http_options"]
        assert http_options.timeout == 90

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
        result = await adapter.complete(messages, model="gemini-3-flash-preview")

        assert result.content == "Hello!"
        assert result.model == "gemini-3-flash-preview"
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
        await adapter.complete(messages, model="gemini-3-flash-preview")

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
            await adapter.complete(
                [Message(role="user", content="Hi")], model="gemini-3-flash-preview"
            )
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
            await adapter.complete(
                [Message(role="user", content="Hi")], model="gemini-3-flash-preview"
            )
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
            await adapter.complete(
                [Message(role="user", content="Hi")], model="gemini-3-flash-preview"
            )
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
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("Connection error")
        )
        mock_genai.Client.return_value = mock_client

        adapter = GeminiAdapter()
        assert await adapter.health_check() is False


class TestGeminiVision:
    """Tests for Gemini vision/image support."""

    @pytest.fixture
    def mock_genai(self):
        """Mock Google GenAI client."""
        with patch("app.adapters.gemini.genai") as mock:
            yield mock

    @pytest.fixture
    def mock_settings(self):
        """Mock settings with API key."""
        with patch("app.adapters.gemini.settings") as mock:
            mock.gemini_api_key = "test-api-key"
            yield mock

    def _create_mock_response(self) -> MagicMock:
        """Create a mock response."""
        mock_response = MagicMock()
        mock_response.text = "I see an image"
        mock_response.usage_metadata = MagicMock()
        mock_response.usage_metadata.prompt_token_count = 100
        mock_response.usage_metadata.candidates_token_count = 10
        mock_response.candidates = [MagicMock(finish_reason="STOP")]
        return mock_response

    @pytest.mark.asyncio
    async def test_complete_with_image_content(self, mock_genai, mock_settings):
        """Test completion with image content blocks."""
        mock_response = self._create_mock_response()
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
        mock_genai.Client.return_value = mock_client

        adapter = GeminiAdapter()

        # Create message with image content
        image_content = [
            {"type": "text", "text": "What do you see in this image?"},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    # Valid base64 for a tiny PNG
                    "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                },
            },
        ]
        messages = [Message(role="user", content=image_content)]

        result = await adapter.complete(messages, model="gemini-3-flash-preview")

        assert result.content == "I see an image"
        assert result.provider == "gemini"

        # Verify the API was called
        mock_client.aio.models.generate_content.assert_called_once()

    @pytest.mark.asyncio
    async def test_build_parts_string(self, mock_genai, mock_settings):
        """Test _build_parts with simple string."""
        adapter = GeminiAdapter()
        parts = adapter._build_parts("Hello")

        assert len(parts) == 1
        assert parts[0].text == "Hello"

    @pytest.mark.asyncio
    async def test_build_parts_mixed_content(self, mock_genai, mock_settings):
        """Test _build_parts with mixed content blocks."""
        adapter = GeminiAdapter()

        content = [
            {"type": "text", "text": "Describe this:"},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    # Simple base64
                    "data": "aGVsbG8=",  # "hello" in base64
                },
            },
        ]
        parts = adapter._build_parts(content)

        assert len(parts) == 2
        assert parts[0].text == "Describe this:"
        # Second part should be image data (Part.from_bytes was called)
