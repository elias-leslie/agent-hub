"""Tests for Claude adapter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.base import (
    AuthenticationError,
    CacheMetrics,
    Message,
    RateLimitError,
)
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


@pytest.fixture
def mock_no_cli():
    """Mock shutil.which to return None (no Claude CLI)."""
    with patch("app.adapters.claude.shutil.which", return_value=None):
        yield


class TestClaudeAdapter:
    """Tests for ClaudeAdapter."""

    def test_init_with_api_key(self, mock_anthropic, mock_settings, mock_no_cli):
        """Test initialization with explicit API key."""
        adapter = ClaudeAdapter(api_key="custom-key")
        assert adapter.provider_name == "claude"
        assert adapter.auth_mode == "api_key"
        mock_anthropic.AsyncAnthropic.assert_called_with(api_key="custom-key")

    def test_init_from_settings(self, mock_anthropic, mock_settings, mock_no_cli):
        """Test initialization from settings."""
        adapter = ClaudeAdapter()
        assert adapter.provider_name == "claude"
        assert adapter.auth_mode == "api_key"
        mock_anthropic.AsyncAnthropic.assert_called_with(api_key="test-api-key")

    def test_init_no_api_key_raises(self, mock_anthropic, mock_settings, mock_no_cli):
        """Test that missing API key and no CLI raises ValueError."""
        mock_settings.anthropic_api_key = ""
        with pytest.raises(ValueError, match="Claude adapter requires"):
            ClaudeAdapter()

    @pytest.mark.asyncio
    async def test_complete_success(self, mock_anthropic, mock_settings, mock_no_cli):
        """Test successful completion."""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Hello!")]
        mock_response.model = "claude-sonnet-4-5-20250514"
        mock_response.usage.input_tokens = 10
        mock_response.usage.output_tokens = 5
        mock_response.usage.cache_creation_input_tokens = 0
        mock_response.usage.cache_read_input_tokens = 0
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
        assert result.cache_metrics is not None

    @pytest.mark.asyncio
    async def test_complete_with_system_message(self, mock_anthropic, mock_settings, mock_no_cli):
        """Test completion with system message (caching disabled)."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Response")]
        mock_response.model = "claude-sonnet-4-5-20250514"
        mock_response.usage.input_tokens = 20
        mock_response.usage.output_tokens = 10
        mock_response.stop_reason = "end_turn"
        # No cache attributes when caching disabled
        del mock_response.usage.cache_creation_input_tokens
        del mock_response.usage.cache_read_input_tokens

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        adapter = ClaudeAdapter()
        messages = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="Hello"),
        ]
        # Disable caching to test simple system message format
        await adapter.complete(messages, model="claude-sonnet-4-5-20250514", enable_caching=False)

        # Verify system was passed correctly (string format when caching disabled)
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "You are helpful"
        assert len(call_kwargs["messages"]) == 1
        assert call_kwargs["messages"][0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_complete_rate_limit(self, mock_anthropic, mock_settings, mock_no_cli):
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
            await adapter.complete(
                [Message(role="user", content="Hi")], model="claude-sonnet-4-5-20250514"
            )
        assert exc_info.value.provider == "claude"
        assert exc_info.value.retriable is True

    @pytest.mark.asyncio
    async def test_complete_auth_error(self, mock_anthropic, mock_settings, mock_no_cli):
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
            await adapter.complete(
                [Message(role="user", content="Hi")], model="claude-sonnet-4-5-20250514"
            )
        assert exc_info.value.provider == "claude"

    @pytest.mark.asyncio
    async def test_health_check_success(self, mock_anthropic, mock_settings, mock_no_cli):
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
    async def test_health_check_failure(self, mock_anthropic, mock_settings, mock_no_cli):
        """Test failed health check."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("Connection error"))
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        adapter = ClaudeAdapter()
        assert await adapter.health_check() is False


class TestClaudeCaching:
    """Tests for Claude prompt caching."""

    @pytest.fixture
    def mock_anthropic(self):
        """Mock Anthropic client."""
        with patch("app.adapters.claude.anthropic") as mock:
            yield mock

    @pytest.fixture
    def mock_settings(self):
        """Mock settings with API key."""
        with patch("app.adapters.claude.settings") as mock:
            mock.anthropic_api_key = "test-api-key"
            yield mock

    @pytest.fixture
    def mock_no_cli(self):
        """Mock shutil.which to return None (no Claude CLI)."""
        with patch("app.adapters.claude.shutil.which", return_value=None):
            yield

    def _create_mock_response(
        self,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> MagicMock:
        """Create a mock response with cache metrics."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Cached response")]
        mock_response.model = "claude-sonnet-4-5-20250514"
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        mock_response.usage.cache_creation_input_tokens = cache_creation_tokens
        mock_response.usage.cache_read_input_tokens = cache_read_tokens
        mock_response.stop_reason = "end_turn"
        return mock_response

    @pytest.mark.asyncio
    async def test_caching_enabled_by_default(self, mock_anthropic, mock_settings, mock_no_cli):
        """Test that caching is enabled by default."""
        mock_response = self._create_mock_response(cache_creation_tokens=500)

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        adapter = ClaudeAdapter()
        messages = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="Hello"),
        ]
        result = await adapter.complete(messages, model="claude-sonnet-4-5-20250514")

        # Verify cache_control was added to system message
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert isinstance(call_kwargs["system"], list)
        assert call_kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}

        # Verify cache metrics returned
        assert result.cache_metrics is not None
        assert result.cache_metrics.cache_creation_input_tokens == 500
        assert result.cache_metrics.cache_read_input_tokens == 0

    @pytest.mark.asyncio
    async def test_caching_disabled(self, mock_anthropic, mock_settings, mock_no_cli):
        """Test that caching can be disabled."""
        mock_response = self._create_mock_response()
        # Remove cache attributes to simulate non-cached response
        del mock_response.usage.cache_creation_input_tokens
        del mock_response.usage.cache_read_input_tokens

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        adapter = ClaudeAdapter()
        messages = [
            Message(role="system", content="You are helpful"),
            Message(role="user", content="Hello"),
        ]
        result = await adapter.complete(
            messages, model="claude-sonnet-4-5-20250514", enable_caching=False
        )

        # Verify cache_control was NOT added
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "You are helpful"

        # No cache metrics when disabled
        assert result.cache_metrics is None

    @pytest.mark.asyncio
    async def test_cache_hit_metrics(self, mock_anthropic, mock_settings, mock_no_cli):
        """Test cache hit metrics are captured correctly."""
        mock_response = self._create_mock_response(
            cache_creation_tokens=0,
            cache_read_tokens=1000,
        )

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        adapter = ClaudeAdapter()
        result = await adapter.complete(
            [Message(role="user", content="Hello")],
            model="claude-sonnet-4-5-20250514",
        )

        assert result.cache_metrics is not None
        assert result.cache_metrics.cache_read_input_tokens == 1000
        assert result.cache_metrics.cache_hit_rate == 1.0  # 100% hit rate

    @pytest.mark.asyncio
    async def test_cache_ttl_options(self, mock_anthropic, mock_settings, mock_no_cli):
        """Test different cache TTL options."""
        mock_response = self._create_mock_response(cache_creation_tokens=500)

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        adapter = ClaudeAdapter()

        # Test 1-hour TTL
        await adapter.complete(
            [
                Message(role="system", content="Stable prompt"),
                Message(role="user", content="Hello"),
            ],
            model="claude-sonnet-4-5-20250514",
            cache_ttl="1h",
        )

        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["system"][0]["cache_control"] == {"type": "1h"}

    @pytest.mark.asyncio
    async def test_user_message_cache_breakpoint(self, mock_anthropic, mock_settings, mock_no_cli):
        """Test that cache breakpoint is added to last user message."""
        mock_response = self._create_mock_response(cache_creation_tokens=500)

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        adapter = ClaudeAdapter()
        messages = [
            Message(role="user", content="First message"),
            Message(role="assistant", content="Response"),
            Message(role="user", content="Second message"),
        ]
        await adapter.complete(messages, model="claude-sonnet-4-5-20250514")

        call_kwargs = mock_client.messages.create.call_args.kwargs
        api_messages = call_kwargs["messages"]

        # First user message should NOT have cache_control
        assert api_messages[0]["content"] == "First message"

        # Last user message should have cache_control
        assert isinstance(api_messages[2]["content"], list)
        assert api_messages[2]["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_cache_metrics_hit_rate_calculation(self):
        """Test CacheMetrics hit rate calculation."""
        # No cache activity
        metrics = CacheMetrics(cache_creation_input_tokens=0, cache_read_input_tokens=0)
        assert metrics.cache_hit_rate == 0.0

        # All cache creation (first request)
        metrics = CacheMetrics(cache_creation_input_tokens=1000, cache_read_input_tokens=0)
        assert metrics.cache_hit_rate == 0.0

        # Full cache hit
        metrics = CacheMetrics(cache_creation_input_tokens=0, cache_read_input_tokens=1000)
        assert metrics.cache_hit_rate == 1.0

        # Partial cache hit
        metrics = CacheMetrics(cache_creation_input_tokens=500, cache_read_input_tokens=500)
        assert metrics.cache_hit_rate == 0.5


class TestClaudeVision:
    """Tests for Claude vision/image support."""

    @pytest.fixture
    def mock_anthropic(self):
        """Mock Anthropic client."""
        with patch("app.adapters.claude.anthropic") as mock:
            yield mock

    @pytest.fixture
    def mock_settings(self):
        """Mock settings with API key."""
        with patch("app.adapters.claude.settings") as mock:
            mock.anthropic_api_key = "test-api-key"
            yield mock

    @pytest.fixture
    def mock_no_cli(self):
        """Mock shutil.which to return None (no Claude CLI)."""
        with patch("app.adapters.claude.shutil.which", return_value=None):
            yield

    def _create_mock_response(self) -> MagicMock:
        """Create a mock response."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="I see an image")]
        mock_response.model = "claude-sonnet-4-5-20250514"
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 10
        mock_response.usage.cache_creation_input_tokens = 0
        mock_response.usage.cache_read_input_tokens = 0
        mock_response.stop_reason = "end_turn"
        return mock_response

    @pytest.mark.asyncio
    async def test_complete_with_image_content(self, mock_anthropic, mock_settings, mock_no_cli):
        """Test completion with image content blocks."""
        mock_response = self._create_mock_response()
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        adapter = ClaudeAdapter()

        # Create message with image content
        image_content = [
            {"type": "text", "text": "What do you see in this image?"},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": "iVBORw0KGgoAAAANSUhEUg==",  # Truncated base64
                },
            },
        ]
        messages = [Message(role="user", content=image_content)]

        result = await adapter.complete(messages, model="claude-sonnet-4-5-20250514")

        assert result.content == "I see an image"
        assert result.provider == "claude"

        # Verify the API was called with correct content format
        call_kwargs = mock_client.messages.create.call_args.kwargs
        api_messages = call_kwargs["messages"]

        assert len(api_messages) == 1
        assert api_messages[0]["role"] == "user"
        # Content should be a list of blocks
        assert isinstance(api_messages[0]["content"], list)
        assert len(api_messages[0]["content"]) == 2
        assert api_messages[0]["content"][0]["type"] == "text"
        assert api_messages[0]["content"][1]["type"] == "image"

    @pytest.mark.asyncio
    async def test_complete_with_mixed_messages(self, mock_anthropic, mock_settings, mock_no_cli):
        """Test completion with both text and image messages."""
        mock_response = self._create_mock_response()
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        adapter = ClaudeAdapter()

        # Mix of string content and image content
        messages = [
            Message(role="user", content="Hello"),  # String content
            Message(role="assistant", content="Hi! How can I help?"),
            Message(
                role="user",
                content=[
                    {"type": "text", "text": "What's this?"},
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": "abc123"},
                    },
                ],
            ),
        ]

        await adapter.complete(messages, model="claude-sonnet-4-5-20250514")

        call_kwargs = mock_client.messages.create.call_args.kwargs
        api_messages = call_kwargs["messages"]

        # First message should be string
        assert api_messages[0]["content"] == "Hello"
        # Second message should be string
        assert api_messages[1]["content"] == "Hi! How can I help?"
        # Third message should be content blocks
        assert isinstance(api_messages[2]["content"], list)
