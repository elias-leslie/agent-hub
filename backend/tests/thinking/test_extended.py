"""Tests for extended thinking data model support."""


from app.constants.models import CLAUDE_SONNET
from app.services.llm_messages import CompletionResult, StreamEvent


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
            model=CLAUDE_SONNET,
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
            model=CLAUDE_SONNET,
            provider="claude",
            input_tokens=100,
            output_tokens=50,
        )
        assert result.thinking_content is None
        assert result.thinking_tokens is None
