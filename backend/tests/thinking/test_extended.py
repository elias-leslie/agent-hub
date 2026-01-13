"""Tests for extended thinking support in Claude adapter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.base import CompletionResult, Message, StreamEvent
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


class TestExtendedThinking:
    """Tests for extended thinking in Claude adapter."""

    def _create_mock_response_with_thinking(
        self,
        content: str = "Response content",
        thinking: str = "Internal reasoning...",
        model: str = "claude-sonnet-4-5-20250514",
    ) -> MagicMock:
        """Create a mock response with thinking blocks."""
        # Create thinking block
        thinking_block = MagicMock()
        thinking_block.type = "thinking"
        thinking_block.thinking = thinking

        # Create text block
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = content

        mock_response = MagicMock()
        mock_response.content = [thinking_block, text_block]
        mock_response.model = model
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        mock_response.usage.cache_creation_input_tokens = 0
        mock_response.usage.cache_read_input_tokens = 0
        mock_response.stop_reason = "end_turn"
        return mock_response

    def _create_mock_response_no_thinking(
        self,
        content: str = "Response content",
        model: str = "claude-sonnet-4-5-20250514",
    ) -> MagicMock:
        """Create a mock response without thinking blocks."""
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = content

        mock_response = MagicMock()
        mock_response.content = [text_block]
        mock_response.model = model
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        mock_response.usage.cache_creation_input_tokens = 0
        mock_response.usage.cache_read_input_tokens = 0
        mock_response.stop_reason = "end_turn"
        return mock_response

    @pytest.mark.asyncio
    async def test_thinking_with_budget_tokens(self, mock_anthropic, mock_settings, mock_no_cli):
        """Test that budget_tokens enables extended thinking."""
        mock_response = self._create_mock_response_with_thinking(
            content="Final answer",
            thinking="Let me think about this carefully...",
        )

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        adapter = ClaudeAdapter()
        messages = [Message(role="user", content="Solve this complex problem")]
        result = await adapter.complete(
            messages,
            model="claude-sonnet-4-5-20250514",
            budget_tokens=10000,
        )

        # Verify thinking parameter was passed
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "thinking" in call_kwargs
        assert call_kwargs["thinking"]["type"] == "enabled"
        assert call_kwargs["thinking"]["budget_tokens"] == 10000
        # Temperature should be forced to 1.0 with thinking
        assert call_kwargs["temperature"] == 1.0

        # Verify result contains thinking content
        assert result.thinking_content == "Let me think about this carefully..."
        assert result.content == "Final answer"

    @pytest.mark.asyncio
    async def test_thinking_without_budget_tokens(self, mock_anthropic, mock_settings, mock_no_cli):
        """Test that completion without budget_tokens does not enable thinking."""
        mock_response = self._create_mock_response_no_thinking(
            content="Direct answer",
        )

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        adapter = ClaudeAdapter()
        messages = [Message(role="user", content="Simple question")]
        result = await adapter.complete(
            messages,
            model="claude-sonnet-4-5-20250514",
        )

        # Verify thinking parameter was NOT passed
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "thinking" not in call_kwargs

        # Verify result has no thinking content
        assert result.thinking_content is None
        assert result.content == "Direct answer"

    @pytest.mark.asyncio
    async def test_thinking_with_tools_uses_beta_api(
        self, mock_anthropic, mock_settings, mock_no_cli
    ):
        """Test that thinking + tools uses interleaved-thinking beta."""
        mock_response = self._create_mock_response_with_thinking()

        # Mock beta API
        mock_client = AsyncMock()
        mock_client.beta.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        adapter = ClaudeAdapter()
        messages = [Message(role="user", content="Use tools with thinking")]

        tools = [
            {
                "name": "calculator",
                "description": "Perform calculations",
                "input_schema": {"type": "object", "properties": {}},
            }
        ]

        await adapter.complete(
            messages,
            model="claude-sonnet-4-5-20250514",
            budget_tokens=5000,
            tools=tools,
        )

        # Verify beta API was called with interleaved-thinking beta
        call_kwargs = mock_client.beta.messages.create.call_args.kwargs
        assert "interleaved-thinking-2025-05-14" in call_kwargs.get("betas", [])

    @pytest.mark.asyncio
    async def test_thinking_forces_temperature_one(
        self, mock_anthropic, mock_settings, mock_no_cli
    ):
        """Test that thinking forces temperature=1.0 even if different is specified."""
        mock_response = self._create_mock_response_with_thinking()

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        adapter = ClaudeAdapter()
        messages = [Message(role="user", content="Test")]

        # Try to use temperature=0.5
        await adapter.complete(
            messages,
            model="claude-sonnet-4-5-20250514",
            temperature=0.5,
            budget_tokens=10000,
        )

        # Verify temperature was forced to 1.0
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["temperature"] == 1.0

    @pytest.mark.asyncio
    async def test_thinking_content_preserved_on_error(
        self, mock_anthropic, mock_settings, mock_no_cli
    ):
        """Test that partial thinking is captured even if request fails later."""
        # Create response with only thinking (simulating partial response)
        thinking_block = MagicMock()
        thinking_block.type = "thinking"
        thinking_block.thinking = "Started thinking about..."

        mock_response = MagicMock()
        mock_response.content = [thinking_block]
        mock_response.model = "claude-sonnet-4-5-20250514"
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 20
        mock_response.usage.cache_creation_input_tokens = 0
        mock_response.usage.cache_read_input_tokens = 0
        mock_response.stop_reason = "max_tokens"  # Truncated

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic.AsyncAnthropic.return_value = mock_client

        adapter = ClaudeAdapter()
        result = await adapter.complete(
            [Message(role="user", content="Test")],
            model="claude-sonnet-4-5-20250514",
            budget_tokens=100,  # Very small budget
        )

        # Thinking should still be captured
        assert result.thinking_content == "Started thinking about..."
        assert result.content == ""  # No text content
        assert result.finish_reason == "max_tokens"


class TestStreamEventThinking:
    """Tests for thinking in StreamEvent."""

    def test_stream_event_thinking_type(self):
        """Test StreamEvent supports thinking type."""
        event = StreamEvent(type="thinking", content="Reasoning...")
        assert event.type == "thinking"
        assert event.content == "Reasoning..."

    def test_stream_event_thinking_tokens(self):
        """Test StreamEvent supports thinking_tokens field."""
        event = StreamEvent(
            type="done",
            input_tokens=100,
            output_tokens=50,
            thinking_tokens=500,
            finish_reason="end_turn",
        )
        assert event.thinking_tokens == 500


class TestCompletionResultThinking:
    """Tests for thinking in CompletionResult."""

    def test_completion_result_with_thinking(self):
        """Test CompletionResult supports thinking fields."""
        result = CompletionResult(
            content="Response",
            model="claude-sonnet-4-5-20250514",
            provider="claude",
            input_tokens=100,
            output_tokens=50,
            thinking_content="Internal reasoning process...",
            thinking_tokens=300,
        )
        assert result.thinking_content == "Internal reasoning process..."
        assert result.thinking_tokens == 300

    def test_completion_result_without_thinking(self):
        """Test CompletionResult defaults for thinking fields."""
        result = CompletionResult(
            content="Response",
            model="claude-sonnet-4-5-20250514",
            provider="claude",
            input_tokens=100,
            output_tokens=50,
        )
        assert result.thinking_content is None
        assert result.thinking_tokens is None
