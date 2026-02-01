"""Unit tests for cross-provider message transformation."""

import pytest

from app.adapters.base import Message
from app.services.message_transform import (
    TransformResult,
    anthropic_normalize_id,
    gemini_normalize_id,
    get_normalizer_for_provider,
    openai_normalize_id,
    transform_messages,
)


class TestTransformMessages:
    """Tests for transform_messages function."""

    def test_simple_text_passthrough(self) -> None:
        """Simple text messages should pass through unchanged."""
        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there"),
        ]
        result = transform_messages(messages, "claude", "claude")
        assert len(result.messages) == 2
        assert result.messages[0].content == "Hello"
        assert result.messages[1].content == "Hi there"

    def test_thinking_block_same_provider(self) -> None:
        """Thinking blocks should be preserved for same provider."""
        messages = [
            Message(
                role="assistant",
                content=[
                    {"type": "thinking", "thinking": "Let me think..."},
                    {"type": "text", "text": "Here's my answer"},
                ],
            ),
        ]
        result = transform_messages(messages, "claude", "anthropic")
        assert result.thinking_converted == 0
        assert len(result.messages) == 1
        content = result.messages[0].content
        assert isinstance(content, list)
        assert content[0]["type"] == "thinking"

    def test_thinking_block_cross_provider(self) -> None:
        """Thinking blocks should be converted to text for different provider."""
        messages = [
            Message(
                role="assistant",
                content=[
                    {"type": "thinking", "thinking": "Let me think..."},
                    {"type": "text", "text": "Here's my answer"},
                ],
            ),
        ]
        result = transform_messages(messages, "claude", "gemini")
        assert result.thinking_converted == 1
        content = result.messages[0].content
        assert isinstance(content, list)
        assert content[0]["type"] == "text"
        assert "[Thinking]" in content[0]["text"]
        assert "Let me think..." in content[0]["text"]

    def test_tool_id_normalization(self) -> None:
        """Tool call IDs should be normalized for target provider."""
        long_id = "a" * 100
        messages = [
            Message(
                role="assistant",
                content=[
                    {"type": "tool_use", "id": long_id, "name": "search", "input": {}},
                ],
            ),
            Message(
                role="user",
                content=[
                    {"type": "tool_result", "tool_use_id": long_id, "content": "result"},
                ],
            ),
        ]
        result = transform_messages(messages, "openai", "claude")
        assert result.tool_ids_normalized >= 1

        tool_use = result.messages[0].content[0]
        assert len(tool_use["id"]) <= 64

        tool_result = result.messages[1].content[0]
        assert tool_result["tool_use_id"] == tool_use["id"]

    def test_orphaned_tool_call_resolution(self) -> None:
        """Orphaned tool calls should get synthetic results."""
        messages = [
            Message(
                role="assistant",
                content=[
                    {"type": "tool_use", "id": "call_123", "name": "search", "input": {}},
                ],
            ),
        ]
        result = transform_messages(messages, "claude", "claude")
        assert result.orphaned_resolved == 1
        assert len(result.messages) == 2

        synthetic = result.messages[1].content
        assert isinstance(synthetic, list)
        assert synthetic[0]["type"] == "tool_result"
        assert synthetic[0]["is_error"] is True

    def test_error_block_filtered(self) -> None:
        """Error blocks should be filtered out."""
        messages = [
            Message(
                role="assistant",
                content=[
                    {"type": "text", "text": "Starting..."},
                    {"type": "error", "error": "Something failed"},
                ],
            ),
        ]
        result = transform_messages(messages, "claude", "claude")
        assert result.errors_filtered == 1
        content = result.messages[0].content
        assert isinstance(content, str)
        assert content == "Starting..."

    def test_no_normalization_flag(self) -> None:
        """Tool IDs should not be normalized when flag is False."""
        long_id = "a" * 100
        messages = [
            Message(
                role="assistant",
                content=[
                    {"type": "tool_use", "id": long_id, "name": "search", "input": {}},
                ],
            ),
        ]
        result = transform_messages(messages, "openai", "claude", normalize_tool_ids=False)
        assert result.tool_ids_normalized == 0
        tool_use = result.messages[0].content[0]
        assert tool_use["id"] == long_id


class TestProviderNormalizers:
    """Tests for provider-specific normalizers."""

    def test_anthropic_normalize_valid(self) -> None:
        """Valid Anthropic IDs should pass through."""
        normalized, original = anthropic_normalize_id("call_123")
        assert normalized == "call_123"
        assert original is None

    def test_anthropic_normalize_long(self) -> None:
        """Long IDs should be hashed for Anthropic."""
        long_id = "a" * 100
        normalized, original = anthropic_normalize_id(long_id)
        assert len(normalized) <= 64
        assert original == long_id

    def test_gemini_normalize_passthrough(self) -> None:
        """Gemini should pass through all IDs."""
        long_id = "a" * 100
        normalized, original = gemini_normalize_id(long_id)
        assert normalized == long_id
        assert original is None

    def test_openai_normalize_like_anthropic(self) -> None:
        """OpenAI normalizer should apply same constraints as Anthropic."""
        long_id = "call|response|tool|very|long"
        normalized1, _ = openai_normalize_id(long_id)
        normalized2, _ = anthropic_normalize_id(long_id)
        assert normalized1 == normalized2

    def test_get_normalizer_for_provider(self) -> None:
        """Should return correct normalizer for each provider."""
        assert get_normalizer_for_provider("claude") == anthropic_normalize_id
        assert get_normalizer_for_provider("anthropic") == anthropic_normalize_id
        assert get_normalizer_for_provider("gemini") == gemini_normalize_id
        assert get_normalizer_for_provider("openai") == openai_normalize_id

    def test_get_normalizer_unknown_fallback(self) -> None:
        """Unknown provider should fallback to anthropic normalizer."""
        normalizer = get_normalizer_for_provider("unknown")
        assert normalizer == anthropic_normalize_id


class TestTransformResult:
    """Tests for TransformResult stats tracking."""

    def test_stats_accumulate(self) -> None:
        """Stats should accumulate across multiple transformations."""
        messages = [
            Message(
                role="assistant",
                content=[
                    {"type": "thinking", "thinking": "Think 1"},
                    {"type": "tool_use", "id": "a" * 100, "name": "tool1", "input": {}},
                ],
            ),
            Message(
                role="assistant",
                content=[
                    {"type": "thinking", "thinking": "Think 2"},
                    {"type": "tool_use", "id": "b" * 100, "name": "tool2", "input": {}},
                    {"type": "error", "error": "Failed"},
                ],
            ),
        ]
        result = transform_messages(messages, "openai", "claude")
        assert result.thinking_converted == 2
        assert result.tool_ids_normalized == 2
        assert result.errors_filtered == 1
        assert result.orphaned_resolved == 2


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_messages(self) -> None:
        """Empty message list should work."""
        result = transform_messages([], "claude", "gemini")
        assert result.messages == []
        assert result.thinking_converted == 0

    def test_mixed_content_types(self) -> None:
        """Messages with mixed content (str and list) should work."""
        messages = [
            Message(role="user", content="Hello"),
            Message(
                role="assistant",
                content=[{"type": "text", "text": "Response"}],
            ),
        ]
        result = transform_messages(messages, "claude", "gemini")
        assert len(result.messages) == 2
        assert result.messages[0].content == "Hello"

    def test_empty_thinking_block_skipped(self) -> None:
        """Empty thinking blocks should be skipped."""
        messages = [
            Message(
                role="assistant",
                content=[
                    {"type": "thinking", "thinking": ""},
                    {"type": "text", "text": "Answer"},
                ],
            ),
        ]
        result = transform_messages(messages, "claude", "gemini")
        content = result.messages[0].content
        assert isinstance(content, str)
        assert content == "Answer"

    def test_multiple_tool_calls_with_results(self) -> None:
        """Multiple tool calls with all results should not create orphans."""
        messages = [
            Message(
                role="assistant",
                content=[
                    {"type": "tool_use", "id": "call_1", "name": "search", "input": {}},
                    {"type": "tool_use", "id": "call_2", "name": "read", "input": {}},
                ],
            ),
            Message(
                role="user",
                content=[
                    {"type": "tool_result", "tool_use_id": "call_1", "content": "r1"},
                    {"type": "tool_result", "tool_use_id": "call_2", "content": "r2"},
                ],
            ),
        ]
        result = transform_messages(messages, "claude", "claude")
        assert result.orphaned_resolved == 0
