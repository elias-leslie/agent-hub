"""Tests for context management and summarization service."""

from unittest.mock import AsyncMock

import pytest

from app.adapters.base import CompletionResult, Message
from app.services.context_manager import (
    DEFAULT_PRESERVE_RECENT,
    SUMMARIZATION_MODEL,
    CompressionResult,
    CompressionStrategy,
    ContextConfig,
    _build_summarization_prompt,
    _split_messages,
    compress_context,
    estimate_compression,
    needs_compression,
    summarize_context,
    summarize_messages,
    truncate_context,
)


class TestSplitMessages:
    """Tests for _split_messages."""

    def test_splits_system_and_conversation(self):
        """Test separating system prompt from conversation."""
        messages = [
            Message(role="system", content="You are helpful."),
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there!"),
            Message(role="user", content="How are you?"),
            Message(role="assistant", content="I'm doing well."),
        ]

        system, old, recent = _split_messages(messages, preserve_recent=1)

        assert system is not None
        assert system.content == "You are helpful."
        assert len(old) == 2  # First user+assistant pair
        assert len(recent) == 2  # Last user+assistant pair

    def test_no_system_message(self):
        """Test handling conversation without system prompt."""
        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there!"),
        ]

        system, old, recent = _split_messages(messages, preserve_recent=1)

        assert system is None
        assert len(old) == 0
        assert len(recent) == 2

    def test_preserve_all_when_short(self):
        """Test preserving all messages when conversation is short."""
        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi!"),
        ]

        system, old, recent = _split_messages(messages, preserve_recent=5)

        assert len(old) == 0
        assert len(recent) == 2

    def test_preserve_recent_count(self):
        """Test correct number of recent messages preserved."""
        messages = [Message(role="user", content=f"Message {i}") for i in range(10)]

        system, old, recent = _split_messages(messages, preserve_recent=2)

        assert len(recent) == 4  # 2 turns * 2 messages
        assert len(old) == 6


class TestBuildSummarizationPrompt:
    """Tests for _build_summarization_prompt."""

    def test_builds_prompt_with_messages(self):
        """Test prompt includes all messages."""
        messages = [
            Message(role="user", content="What's the plan?"),
            Message(role="assistant", content="We'll build a feature."),
        ]

        prompt = _build_summarization_prompt(messages)

        assert "USER: What's the plan?" in prompt
        assert "ASSISTANT: We'll build a feature." in prompt
        assert "SUMMARY:" in prompt

    def test_empty_messages(self):
        """Test prompt for empty message list."""
        prompt = _build_summarization_prompt([])

        assert "SUMMARY:" in prompt


class TestSummarizeMessages:
    """Tests for summarize_messages."""

    @pytest.mark.asyncio
    async def test_calls_adapter_with_haiku(self):
        """Test summarization uses Haiku model."""
        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi!"),
        ]

        mock_adapter = AsyncMock()
        mock_adapter.complete.return_value = CompletionResult(
            content="- User said hello\n- Assistant responded",
            model=SUMMARIZATION_MODEL,
            provider="claude",
            input_tokens=100,
            output_tokens=20,
        )

        result = await summarize_messages(messages, mock_adapter)

        assert "User said hello" in result
        mock_adapter.complete.assert_awaited_once()
        call_kwargs = mock_adapter.complete.call_args.kwargs
        assert call_kwargs["model"] == SUMMARIZATION_MODEL
        assert call_kwargs["temperature"] == 0.3

    @pytest.mark.asyncio
    async def test_empty_messages_returns_empty(self):
        """Test empty message list returns empty string."""
        mock_adapter = AsyncMock()
        result = await summarize_messages([], mock_adapter)
        assert result == ""
        mock_adapter.complete.assert_not_awaited()


class TestTruncateContext:
    """Tests for truncate_context."""

    def test_truncates_old_messages(self):
        """Test truncation removes old messages."""
        messages = [
            Message(role="system", content="System prompt"),
            Message(role="user", content="Old message 1"),
            Message(role="assistant", content="Old response 1"),
            Message(role="user", content="Old message 2"),
            Message(role="assistant", content="Old response 2"),
            Message(role="user", content="Recent message"),
            Message(role="assistant", content="Recent response"),
        ]

        result = truncate_context(messages, "claude-sonnet-4-5", preserve_recent=1)

        # Should have: system + 2 recent messages
        assert len(result.messages) == 3
        assert result.messages[0].role == "system"
        assert result.messages[1].content == "Recent message"
        assert result.strategy_used == CompressionStrategy.TRUNCATE
        assert result.messages_summarized == 4

    def test_preserves_system_prompt(self):
        """Test system prompt is always preserved."""
        messages = [
            Message(role="system", content="Important instructions"),
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi!"),
        ]

        result = truncate_context(messages, "claude-sonnet-4-5", preserve_recent=1)

        assert result.messages[0].role == "system"
        assert result.messages[0].content == "Important instructions"

    def test_calculates_compression_ratio(self):
        """Test compression ratio is calculated."""
        messages = [
            Message(role="user", content="A" * 1000),
            Message(role="assistant", content="B" * 1000),
            Message(role="user", content="C" * 100),
            Message(role="assistant", content="D" * 100),
        ]

        result = truncate_context(messages, "claude-sonnet-4-5", preserve_recent=1)

        assert result.compression_ratio < 1.0
        assert result.compressed_tokens < result.original_tokens


class TestSummarizeContext:
    """Tests for summarize_context."""

    @pytest.mark.asyncio
    async def test_summarizes_old_messages(self):
        """Test old messages are summarized."""
        messages = [
            Message(role="system", content="System prompt"),
            Message(role="user", content="Old discussion about X"),
            Message(role="assistant", content="X is important because..."),
            Message(role="user", content="Recent question"),
            Message(role="assistant", content="Recent answer"),
        ]

        mock_adapter = AsyncMock()
        mock_adapter.complete.return_value = CompletionResult(
            content="- Discussed X and its importance",
            model=SUMMARIZATION_MODEL,
            provider="claude",
            input_tokens=100,
            output_tokens=20,
        )

        result = await summarize_context(
            messages, "claude-sonnet-4-5", mock_adapter, preserve_recent=1
        )

        assert result.strategy_used == CompressionStrategy.SUMMARIZE
        assert result.summary == "- Discussed X and its importance"
        assert result.messages_summarized == 2
        # Should have: system + summary context + ack + recent
        assert len(result.messages) == 5

    @pytest.mark.asyncio
    async def test_no_summarization_needed(self):
        """Test short conversations aren't summarized."""
        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi!"),
        ]

        mock_adapter = AsyncMock()

        result = await summarize_context(
            messages, "claude-sonnet-4-5", mock_adapter, preserve_recent=5
        )

        assert result.messages == messages
        assert result.summary is None
        mock_adapter.complete.assert_not_awaited()


class TestCompressContext:
    """Tests for compress_context."""

    @pytest.mark.asyncio
    async def test_no_compression_under_target(self):
        """Test no compression when under target ratio."""
        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi!"),
        ]

        config = ContextConfig(target_ratio=0.5)
        result = await compress_context(messages, "claude-sonnet-4-5", config)

        assert result.messages == messages
        assert result.compression_ratio == 1.0

    @pytest.mark.asyncio
    async def test_truncate_strategy(self):
        """Test truncate strategy is applied."""
        # Create messages that exceed target - use smaller content with very low target
        messages = [
            Message(role="user", content="X" * 1000),
            Message(role="assistant", content="Y" * 1000),
            Message(role="user", content="Recent"),
            Message(role="assistant", content="Response"),
        ]

        config = ContextConfig(
            strategy=CompressionStrategy.TRUNCATE,
            target_ratio=0.001,  # Very low target to trigger compression
            preserve_recent=1,
        )
        result = await compress_context(messages, "claude-sonnet-4-5", config)

        assert result.strategy_used == CompressionStrategy.TRUNCATE
        assert len(result.messages) == 2  # Only recent

    @pytest.mark.asyncio
    async def test_summarize_strategy_requires_adapter(self):
        """Test summarize strategy fails without adapter."""
        # Use small content with very low target to trigger compression
        messages = [
            Message(role="user", content="X" * 1000),
            Message(role="assistant", content="Y" * 1000),
        ]

        config = ContextConfig(
            strategy=CompressionStrategy.SUMMARIZE,
            target_ratio=0.001,  # Very low to trigger compression
        )

        with pytest.raises(ValueError, match="Adapter required"):
            await compress_context(messages, "claude-sonnet-4-5", config)

    @pytest.mark.asyncio
    async def test_hybrid_falls_back_to_truncate(self):
        """Test hybrid strategy falls back to truncation on error."""
        # Use small content with very low target to trigger compression
        messages = [
            Message(role="user", content="X" * 1000),
            Message(role="assistant", content="Y" * 1000),
            Message(role="user", content="Recent"),
            Message(role="assistant", content="Response"),
        ]

        mock_adapter = AsyncMock()
        mock_adapter.complete.side_effect = Exception("API error")

        config = ContextConfig(
            strategy=CompressionStrategy.HYBRID,
            target_ratio=0.001,  # Very low to trigger compression
            preserve_recent=1,
        )
        result = await compress_context(messages, "claude-sonnet-4-5", config, mock_adapter)

        assert result.strategy_used == CompressionStrategy.TRUNCATE


class TestNeedsCompression:
    """Tests for needs_compression."""

    def test_returns_true_above_threshold(self):
        """Test returns true when above threshold."""
        # Use smaller content with low threshold to test the logic
        # Small message ~10 tokens, threshold 0.001% of 200K = 2 tokens
        messages = [Message(role="user", content="X" * 100)]

        # Very low threshold (0.001%) to ensure even small content triggers
        assert needs_compression(messages, "claude-sonnet-4-5", threshold_percent=0.001)

    def test_returns_false_below_threshold(self):
        """Test returns false when below threshold."""
        messages = [Message(role="user", content="Hello")]

        assert not needs_compression(messages, "claude-sonnet-4-5", threshold_percent=75)


class TestEstimateCompression:
    """Tests for estimate_compression."""

    def test_estimates_compression_results(self):
        """Test compression estimates are reasonable."""
        messages = [
            Message(role="system", content="System prompt"),
            Message(role="user", content="Old message " * 100),
            Message(role="assistant", content="Old response " * 100),
            Message(role="user", content="Recent"),
            Message(role="assistant", content="Response"),
        ]

        estimate = estimate_compression(messages, "claude-sonnet-4-5", preserve_recent=1)

        assert estimate["original_tokens"] > 0
        assert estimate["messages_to_summarize"] == 2
        assert estimate["messages_to_preserve"] == 3  # system + 2 recent
        assert estimate["truncation"]["compression_ratio"] < 1.0
        assert estimate["summarization"]["compression_ratio"] < 1.0


class TestContextConfig:
    """Tests for ContextConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = ContextConfig()

        assert config.strategy == CompressionStrategy.HYBRID
        assert config.preserve_recent == DEFAULT_PRESERVE_RECENT
        assert config.target_ratio == 0.5
        assert config.summarization_enabled is True

    def test_custom_values(self):
        """Test custom configuration."""
        config = ContextConfig(
            strategy=CompressionStrategy.TRUNCATE,
            preserve_recent=10,
            target_ratio=0.3,
        )

        assert config.strategy == CompressionStrategy.TRUNCATE
        assert config.preserve_recent == 10
        assert config.target_ratio == 0.3


class TestCompressionResult:
    """Tests for CompressionResult dataclass."""

    def test_creates_result(self):
        """Test creating compression result."""
        result = CompressionResult(
            messages=[Message(role="user", content="Hello")],
            original_tokens=1000,
            compressed_tokens=500,
            strategy_used=CompressionStrategy.SUMMARIZE,
            summary="Summarized content",
            messages_summarized=5,
            compression_ratio=0.5,
        )

        assert len(result.messages) == 1
        assert result.original_tokens == 1000
        assert result.summary == "Summarized content"


class TestCompressionStrategy:
    """Tests for CompressionStrategy enum."""

    def test_strategy_values(self):
        """Test strategy enum values."""
        assert CompressionStrategy.TRUNCATE.value == "truncate"
        assert CompressionStrategy.SUMMARIZE.value == "summarize"
        assert CompressionStrategy.HYBRID.value == "hybrid"

    def test_strategy_from_string(self):
        """Test creating strategy from string."""
        assert CompressionStrategy("truncate") == CompressionStrategy.TRUNCATE
        assert CompressionStrategy("summarize") == CompressionStrategy.SUMMARIZE
