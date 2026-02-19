"""Unit tests for cross-provider message transformation."""

from app.adapters.base import Message
from app.services.message_transform import transform_messages


class TestTransformMessages:
    """Tests for transform_messages function."""

    def test_simple_text_passthrough(self) -> None:
        """Simple text messages should pass through unchanged."""
        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there"),
        ]
        result = transform_messages(messages, "claude", "claude")
        assert len(result) == 2
        assert result[0].content == "Hello"
        assert result[1].content == "Hi there"

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
        assert len(result) == 1
        content = result[0].content
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
        content = result[0].content
        assert isinstance(content, list)
        assert content[0]["type"] == "text"
        assert "[Previous reasoning]" in content[0]["text"]
        assert "Let me think..." in content[0]["text"]

    def test_tool_id_normalization_for_anthropic(self) -> None:
        """Long tool call IDs should be normalized when targeting Claude."""
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

        tool_use = result[0].content[0]
        assert len(tool_use["id"]) <= 64

        tool_result = result[1].content[0]
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
        # Should have original message + synthetic tool_result message
        assert len(result) == 2

        synthetic = result[1].content
        assert isinstance(synthetic, list)
        assert synthetic[0]["type"] == "tool_result"
        assert synthetic[0]["tool_use_id"] == "call_123"

    def test_error_block_filtered(self) -> None:
        """Error-only assistant messages should be filtered out."""
        messages = [
            Message(role="user", content="Hello"),
            Message(
                role="assistant",
                content=[
                    {"type": "error", "error": "Something failed"},
                ],
            ),
            Message(role="user", content="Try again"),
        ]
        result = transform_messages(messages, "claude", "claude")
        # Error-only assistant message should be removed
        assert len(result) == 2
        assert result[0].content == "Hello"
        assert result[1].content == "Try again"

    def test_no_normalization_for_non_anthropic(self) -> None:
        """Tool IDs should not be normalized when targeting non-Anthropic providers."""
        long_id = "a" * 100
        messages = [
            Message(
                role="assistant",
                content=[
                    {"type": "tool_use", "id": long_id, "name": "search", "input": {}},
                ],
            ),
        ]
        result = transform_messages(messages, "claude", "gemini")
        tool_use = result[0].content[0]
        assert tool_use["id"] == long_id


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_messages(self) -> None:
        """Empty message list should work."""
        result = transform_messages([], "claude", "gemini")
        assert result == []

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
        assert len(result) == 2
        assert result[0].content == "Hello"

    def test_empty_thinking_block_produces_placeholder(self) -> None:
        """Empty thinking blocks should be converted to a '[Reasoning omitted]' placeholder.

        Previously empty thinking blocks were silently dropped, which could cause
        them to be removed by the error filter (empty text blocks are treated as
        errors).  Now they always emit a visible placeholder.
        """
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
        content = result[0].content
        assert isinstance(content, list)
        # Both blocks must be present: placeholder + original text
        assert len(content) == 2
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "[Reasoning omitted]"
        assert content[1]["type"] == "text"
        assert content[1]["text"] == "Answer"

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
        # No orphaned tool calls, so no synthetic messages added
        assert len(result) == 2

    def test_does_not_mutate_original(self) -> None:
        """transform_messages should not mutate the original messages."""
        messages = [
            Message(
                role="assistant",
                content=[
                    {"type": "thinking", "thinking": "Let me think..."},
                    {"type": "text", "text": "Answer"},
                ],
            ),
        ]
        original_content = messages[0].content[0].copy()
        transform_messages(messages, "claude", "gemini")
        # Original should be unchanged
        assert messages[0].content[0] == original_content
