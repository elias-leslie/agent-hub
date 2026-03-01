"""Tests for Gemini adapter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters._errors_types import ProviderError
from app.adapters.base import AuthenticationError, CompletionResult, Message, RateLimitError
from app.adapters.gemini import GeminiAdapter
from app.constants.models import GEMINI_FLASH


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
        """Test that SDK timeout is configured to 300 seconds (300000ms)."""
        GeminiAdapter()
        call_kwargs = mock_genai.Client.call_args.kwargs
        http_options = call_kwargs["http_options"]
        assert http_options.timeout == 300_000  # 300 seconds in milliseconds

    def test_init_no_api_key_falls_back_to_adc(self, mock_genai, mock_settings):
        """Test that missing API key falls back to ADC."""
        mock_settings.gemini_api_key = ""
        adapter = GeminiAdapter()
        assert adapter._auth_mode == "adc"

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
        result = await adapter.complete(messages, model=GEMINI_FLASH)

        assert result.content == "Hello!"
        assert result.model == GEMINI_FLASH
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
        await adapter.complete(messages, model=GEMINI_FLASH)

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
                [Message(role="user", content="Hi")], model=GEMINI_FLASH
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
                [Message(role="user", content="Hi")], model=GEMINI_FLASH
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
                [Message(role="user", content="Hi")], model=GEMINI_FLASH
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

        result = await adapter.complete(messages, model=GEMINI_FLASH)

        assert result.content == "I see an image"
        assert result.provider == "gemini"

        # Verify the API was called
        mock_client.aio.models.generate_content.assert_called_once()


class TestGeminiOAuthFallback:
    """Tests for OAuth → API key fallback when rate-limited."""

    @pytest.mark.asyncio
    async def test_complete_falls_back_to_api_key_on_oauth_rate_limit(self):
        """When OAuth gets 429, complete() should fall back to SDK/API key."""
        expected = CompletionResult(
            content="SDK response",
            model=GEMINI_FLASH,
            provider="gemini",
            input_tokens=10,
            output_tokens=5,
        )

        with (
            patch("app.adapters.gemini.resolve_api_key", return_value="test-key"),
            patch("app.adapters.gemini.resolve_oauth_data", return_value={
                "access_token": "tok", "project_id": "proj", "refresh_token": "ref",
            }),
            patch("app.adapters.gemini.get_gemini_auth_preference", return_value="oauth"),
            patch("app.adapters.gemini.make_cloudcode_client") as mock_cc_factory,
            patch("app.adapters.gemini.make_sdk_client") as mock_sdk_factory,
            patch("app.adapters.gemini.settings") as mock_settings,
            patch("app.adapters.gemini.cloudcode_complete", new_callable=AsyncMock) as mock_cc_complete,
            patch("app.adapters.gemini.sdk_complete", new_callable=AsyncMock) as mock_sdk_complete,
        ):
            mock_settings.gemini_api_key = "test-key"
            mock_cc_factory.return_value = MagicMock()
            mock_sdk_factory.return_value = MagicMock()

            # OAuth raises retriable ProviderError
            mock_cc_complete.side_effect = ProviderError(
                "CloudCode completion error: 429", provider="gemini", retriable=True,
            )
            mock_sdk_complete.return_value = expected

            adapter = GeminiAdapter()
            assert adapter._auth_mode == "oauth"
            assert adapter._has_api_key_fallback()

            result = await adapter.complete(
                [Message(role="user", content="Hi")], model=GEMINI_FLASH,
            )

            assert result.content == "SDK response"
            mock_cc_complete.assert_called_once()
            mock_sdk_complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_complete_does_not_fallback_on_non_retriable_error(self):
        """Non-retriable errors should propagate, not fall back."""
        with (
            patch("app.adapters.gemini.resolve_api_key", return_value="test-key"),
            patch("app.adapters.gemini.resolve_oauth_data", return_value={
                "access_token": "tok", "project_id": "proj", "refresh_token": "ref",
            }),
            patch("app.adapters.gemini.get_gemini_auth_preference", return_value="oauth"),
            patch("app.adapters.gemini.make_cloudcode_client") as mock_cc_factory,
            patch("app.adapters.gemini.make_sdk_client") as mock_sdk_factory,
            patch("app.adapters.gemini.settings") as mock_settings,
            patch("app.adapters.gemini.cloudcode_complete", new_callable=AsyncMock) as mock_cc_complete,
        ):
            mock_settings.gemini_api_key = "test-key"
            mock_cc_factory.return_value = MagicMock()
            mock_sdk_factory.return_value = MagicMock()

            mock_cc_complete.side_effect = ProviderError(
                "Auth failed", provider="gemini", retriable=False,
            )

            adapter = GeminiAdapter()
            with pytest.raises(ProviderError, match="Auth failed"):
                await adapter.complete(
                    [Message(role="user", content="Hi")], model=GEMINI_FLASH,
                )

    @pytest.mark.asyncio
    async def test_complete_no_fallback_without_api_key(self):
        """When no API key exists, 429 should propagate even if retriable."""
        with (
            patch("app.adapters.gemini.resolve_api_key", return_value=None),
            patch("app.adapters.gemini.resolve_oauth_data", return_value={
                "access_token": "tok", "project_id": "proj", "refresh_token": "ref",
            }),
            patch("app.adapters.gemini.get_gemini_auth_preference", return_value="oauth"),
            patch("app.adapters.gemini.make_cloudcode_client") as mock_cc_factory,
            patch("app.adapters.gemini.settings") as mock_settings,
            patch("app.adapters.gemini.cloudcode_complete", new_callable=AsyncMock) as mock_cc_complete,
        ):
            mock_settings.gemini_api_key = ""
            mock_cc_factory.return_value = MagicMock()

            mock_cc_complete.side_effect = ProviderError(
                "429 rate limited", provider="gemini", retriable=True,
            )

            adapter = GeminiAdapter()
            assert not adapter._has_api_key_fallback()

            with pytest.raises(ProviderError, match="429 rate limited"):
                await adapter.complete(
                    [Message(role="user", content="Hi")], model=GEMINI_FLASH,
                )

