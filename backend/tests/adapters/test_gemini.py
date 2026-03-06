"""Tests for Gemini adapter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters._errors_types import ProviderError
from app.adapters.base import (
    AuthenticationError,
    CompletionResult,
    Message,
    RateLimitError,
    StreamEvent,
)
from app.adapters.gemini import GeminiAdapter
from app.constants.models import GEMINI_FLASH, GEMINI_IMAGE


@pytest.fixture
def mock_genai():
    """Mock Google GenAI client."""
    with patch("app.adapters.gemini_adapter_settings.genai") as mock:
        yield mock


class TestGeminiAdapter:
    """Tests for GeminiAdapter."""

    def test_init_with_api_key(self, mock_genai):
        """Test initialization with explicit API key."""
        adapter = GeminiAdapter(api_key="custom-key")
        assert adapter.provider_name == "gemini"
        # Check that Client was called with api_key and http_options
        call_kwargs = mock_genai.Client.call_args.kwargs
        assert call_kwargs["api_key"] == "custom-key"
        assert "http_options" in call_kwargs

    def test_init_from_credential_manager(self, mock_genai):
        """Test initialization from credential manager."""
        from app.services.credential_manager import CredentialManager

        CredentialManager.reset()
        cm = CredentialManager.get_instance()
        cm.set("gemini", "api_key", "from-cm")
        cm._initialized = True

        try:
            adapter = GeminiAdapter()
            assert adapter.provider_name == "gemini"
            call_kwargs = mock_genai.Client.call_args.kwargs
            assert call_kwargs["api_key"] == "from-cm"
            assert "http_options" in call_kwargs
        finally:
            CredentialManager.reset()

    def test_init_with_sdk_timeout(self, mock_genai):
        """Test that SDK timeout is configured to 300 seconds (300000ms)."""
        GeminiAdapter(api_key="test-key")
        call_kwargs = mock_genai.Client.call_args.kwargs
        http_options = call_kwargs["http_options"]
        assert http_options.timeout == 300_000  # 300 seconds in milliseconds

    def test_init_no_api_key_falls_back_to_adc(self, mock_genai):
        """Test that missing API key falls back to ADC."""
        adapter = GeminiAdapter()
        assert adapter._auth_mode == "adc"

    @pytest.mark.asyncio
    async def test_complete_success(self, mock_genai):
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

        adapter = GeminiAdapter(api_key="test-key")
        messages = [Message(role="user", content="Hi")]
        result = await adapter.complete(messages, model=GEMINI_FLASH)

        assert result.content == "Hello!"
        assert result.model == GEMINI_FLASH
        assert result.provider == "gemini"
        assert result.input_tokens == 10
        assert result.output_tokens == 5

    @pytest.mark.asyncio
    async def test_complete_with_system_message(self, mock_genai):
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

        adapter = GeminiAdapter(api_key="test-key")
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
    async def test_complete_rate_limit(self, mock_genai):
        """Test rate limit handling."""
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("429 Too Many Requests")
        )
        mock_genai.Client.return_value = mock_client

        adapter = GeminiAdapter(api_key="test-key")
        with pytest.raises(RateLimitError) as exc_info:
            await adapter.complete(
                [Message(role="user", content="Hi")], model=GEMINI_FLASH
            )
        assert exc_info.value.provider == "gemini"
        assert exc_info.value.retriable is True

    @pytest.mark.asyncio
    async def test_complete_auth_error(self, mock_genai):
        """Test authentication error handling."""
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("401 Invalid API key")
        )
        mock_genai.Client.return_value = mock_client

        adapter = GeminiAdapter(api_key="test-key")
        with pytest.raises(AuthenticationError) as exc_info:
            await adapter.complete(
                [Message(role="user", content="Hi")], model=GEMINI_FLASH
            )
        assert exc_info.value.provider == "gemini"

    @pytest.mark.asyncio
    async def test_complete_quota_error(self, mock_genai):
        """Test quota exceeded handling."""
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("quota exceeded for this project")
        )
        mock_genai.Client.return_value = mock_client

        adapter = GeminiAdapter(api_key="test-key")
        with pytest.raises(RateLimitError) as exc_info:
            await adapter.complete(
                [Message(role="user", content="Hi")], model=GEMINI_FLASH
            )
        assert exc_info.value.provider == "gemini"

    @pytest.mark.asyncio
    async def test_health_check_success(self, mock_genai):
        """Test successful health check via models.get (zero tokens)."""
        mock_model_info = MagicMock()

        mock_client = MagicMock()
        mock_client.aio.models.get = AsyncMock(return_value=mock_model_info)
        mock_genai.Client.return_value = mock_client

        adapter = GeminiAdapter(api_key="test-key")
        assert await adapter.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, mock_genai):
        """Test failed health check."""
        mock_client = MagicMock()
        mock_client.aio.models.get = AsyncMock(
            side_effect=Exception("Connection error")
        )
        mock_genai.Client.return_value = mock_client

        adapter = GeminiAdapter(api_key="test-key")
        assert await adapter.health_check() is False


class TestGeminiVision:
    """Tests for Gemini vision/image support."""

    @pytest.fixture
    def mock_genai(self):
        """Mock Google GenAI client."""
        with patch("app.adapters.gemini_adapter_settings.genai") as mock:
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
    async def test_complete_with_image_content(self, mock_genai):
        """Test completion with image content blocks."""
        mock_response = self._create_mock_response()
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
        mock_genai.Client.return_value = mock_client

        adapter = GeminiAdapter(api_key="test-key")

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
            patch("app.adapters.gemini.cloudcode_complete", new_callable=AsyncMock) as mock_cc_complete,
            patch("app.adapters.gemini.sdk_complete", new_callable=AsyncMock) as mock_sdk_complete,
        ):
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
            patch("app.adapters.gemini.cloudcode_complete", new_callable=AsyncMock) as mock_cc_complete,
        ):
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
            patch("app.adapters.gemini.cloudcode_complete", new_callable=AsyncMock) as mock_cc_complete,
        ):
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


class TestGeminiMultiKeyBehavior:
    """Tests for multi-key cache refresh and failover behavior."""

    @pytest.mark.asyncio
    async def test_complete_tries_multiple_api_keys_in_order(self):
        """Rate-limited first key should fall through to the second key."""
        expected = CompletionResult(
            content="Second key succeeded",
            model=GEMINI_FLASH,
            provider="gemini",
            input_tokens=12,
            output_tokens=7,
        )
        client_1 = MagicMock(name="client-1")
        client_2 = MagicMock(name="client-2")

        with (
            patch("app.adapters.gemini.resolve_api_key", return_value=None),
            patch("app.adapters.gemini.resolve_api_keys", return_value=["k1", "k2"]),
            patch("app.adapters.gemini.resolve_oauth_data", return_value=None),
            patch("app.adapters.gemini.get_gemini_auth_preference", return_value="api_key"),
            patch("app.adapters.gemini.pick_auth_mode", return_value=("adc", MagicMock(), None)),
            patch("app.adapters.gemini.make_sdk_client", side_effect=[client_1, client_2]),
            patch("app.adapters.gemini.sdk_complete", new_callable=AsyncMock) as mock_sdk_complete,
        ):
            mock_sdk_complete.side_effect = [
                ProviderError("429 rate limited", provider="gemini", retriable=True),
                expected,
            ]
            adapter = GeminiAdapter()
            result = await adapter.complete([Message(role="user", content="Hi")], model=GEMINI_FLASH)

            assert result.content == "Second key succeeded"
            assert mock_sdk_complete.await_count == 2

    def test_refresh_api_key_allows_empty_key_set(self):
        """When keys are removed from DB, in-memory key list should clear too."""
        with (
            patch("app.adapters.gemini.resolve_api_key", return_value=None),
            patch("app.adapters.gemini.resolve_api_keys", side_effect=[["k1"], []]),
            patch("app.adapters.gemini.resolve_oauth_data", return_value=None),
            patch("app.adapters.gemini.get_gemini_auth_preference", return_value="api_key"),
            patch("app.adapters.gemini.pick_auth_mode", return_value=("api_key", MagicMock(), None)),
            patch("app.adapters.gemini.make_sdk_client", side_effect=[MagicMock()]),
        ):
            adapter = GeminiAdapter()
            assert adapter._api_keys == ["k1"]

            adapter._refresh_api_key()
            assert adapter._api_keys == []
            assert adapter._sdk_clients == []
            assert adapter._client is None

    @pytest.mark.asyncio
    async def test_image_model_without_sdk_client_raises_provider_error(self):
        """Image models must fail with clear error if no API-key SDK client exists."""
        with (
            patch("app.adapters.gemini.resolve_api_key", return_value=None),
            patch("app.adapters.gemini.resolve_api_keys", return_value=[]),
            patch("app.adapters.gemini.resolve_oauth_data", return_value={
                "access_token": "tok", "project_id": "proj", "refresh_token": "ref",
            }),
            patch("app.adapters.gemini.get_gemini_auth_preference", return_value="oauth"),
            patch("app.adapters.gemini.pick_auth_mode", return_value=("oauth", None, MagicMock())),
        ):
            adapter = GeminiAdapter()
            with pytest.raises(ProviderError, match="API key is not configured"):
                await adapter.complete([Message(role="user", content="Draw")], model=GEMINI_IMAGE)

    @pytest.mark.asyncio
    async def test_stream_fails_over_to_next_key_on_retryable_error(self):
        """Streaming should retry next key when first key errors before content."""
        client_1 = MagicMock(name="client-1")
        client_2 = MagicMock(name="client-2")

        async def fake_sdk_stream(client, *_args, **_kwargs):
            if client is client_1:
                yield StreamEvent(type="error", error="rate limit exceeded")
                return
            yield StreamEvent(type="content", content="hello")
            yield StreamEvent(type="done", input_tokens=1, output_tokens=1, finish_reason="STOP")

        with (
            patch("app.adapters.gemini.resolve_api_key", return_value=None),
            patch("app.adapters.gemini.resolve_api_keys", return_value=["k1", "k2"]),
            patch("app.adapters.gemini.resolve_oauth_data", return_value=None),
            patch("app.adapters.gemini.get_gemini_auth_preference", return_value="api_key"),
            patch("app.adapters.gemini.pick_auth_mode", return_value=("api_key", MagicMock(), None)),
            patch("app.adapters.gemini.make_sdk_client", side_effect=[client_1, client_2]),
            patch("app.adapters.gemini.sdk_stream", new=fake_sdk_stream),
        ):
            adapter = GeminiAdapter()
            events = [event async for event in adapter.stream([Message(role="user", content="hi")], GEMINI_FLASH)]

        assert [e.type for e in events] == ["content", "done"]
        assert events[0].content == "hello"
