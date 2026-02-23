"""Tests for context compaction — in-memory message pruning."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.complete.context_compaction import maybe_compact_context

# Patch targets at the source modules (imports are inside the function body)
_TOKEN_COUNTER = "app.services.token_counter"
_ADAPTER_REGISTRY = "app.adapters.registry"


def _make_messages(count: int, system: bool = True) -> list[dict[str, str]]:
    """Build a message list with alternating user/assistant messages."""
    msgs: list[dict[str, str]] = []
    if system:
        msgs.append({"role": "system", "content": "You are a helpful assistant."})
    for i in range(count):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": f"Message {i}: " + "x" * 200})
    return msgs


class TestMaybeCompactContext:
    """Tests for maybe_compact_context()."""

    @pytest.mark.asyncio
    async def test_noop_under_threshold(self):
        """No compaction when usage is below threshold."""
        messages = _make_messages(10)
        with (
            patch(
                f"{_TOKEN_COUNTER}.count_message_tokens",
                return_value=5000,
            ),
            patch(
                f"{_TOKEN_COUNTER}.get_context_limit",
                return_value=100_000,
            ),
        ):
            result, compacted = await maybe_compact_context(messages, "claude-sonnet-4-6")

        assert compacted is False
        assert result is messages

    @pytest.mark.asyncio
    async def test_noop_too_few_messages(self):
        """No compaction when there aren't enough messages to split."""
        messages = _make_messages(4)  # system + 4 = 5 total, below keep_recent*2+2=14
        result, compacted = await maybe_compact_context(messages, "claude-sonnet-4-6")

        assert compacted is False
        assert result is messages

    @pytest.mark.asyncio
    async def test_compacts_when_over_threshold(self):
        """Compaction triggers when usage exceeds threshold."""
        messages = _make_messages(20)

        mock_adapter_result = MagicMock()
        mock_adapter_result.content = "Summary of earlier conversation."
        mock_adapter = AsyncMock()
        mock_adapter.complete = AsyncMock(return_value=mock_adapter_result)

        with (
            patch(
                f"{_TOKEN_COUNTER}.count_message_tokens",
                side_effect=[80_000, 10_000],  # First call: over threshold, second: result
            ),
            patch(
                f"{_TOKEN_COUNTER}.get_context_limit",
                return_value=100_000,
            ),
            patch(
                f"{_ADAPTER_REGISTRY}.get_adapter",
                return_value=mock_adapter,
            ),
        ):
            result, compacted = await maybe_compact_context(
                messages, "claude-sonnet-4-6", keep_recent=4
            )

        assert compacted is True
        # Should have: system + summary + 8 protected messages (4 pairs)
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "You are a helpful assistant."
        assert "[Context Summary" in result[1]["content"]
        assert "Summary of earlier conversation" in result[1]["content"]
        # Protected messages preserved at the end
        assert len(result) > 2

    @pytest.mark.asyncio
    async def test_system_messages_preserved(self):
        """System messages are kept at the front, not compacted."""
        messages = [
            {"role": "system", "content": "System prompt here."},
            {"role": "system", "content": "Memory injection here."},
            *_make_messages(20, system=False),
        ]

        mock_adapter_result = MagicMock()
        mock_adapter_result.content = "Summarized conversation."
        mock_adapter = AsyncMock()
        mock_adapter.complete = AsyncMock(return_value=mock_adapter_result)

        with (
            patch(
                f"{_TOKEN_COUNTER}.count_message_tokens",
                side_effect=[85_000, 8_000],
            ),
            patch(
                f"{_TOKEN_COUNTER}.get_context_limit",
                return_value=100_000,
            ),
            patch(
                f"{_ADAPTER_REGISTRY}.get_adapter",
                return_value=mock_adapter,
            ),
        ):
            result, compacted = await maybe_compact_context(messages, "claude-sonnet-4-6")

        assert compacted is True
        assert result[0]["content"] == "System prompt here."
        assert result[1]["content"] == "Memory injection here."
        assert "[Context Summary" in result[2]["content"]

    @pytest.mark.asyncio
    async def test_summary_failure_returns_unchanged(self):
        """If summarization fails, return original messages."""
        messages = _make_messages(20)

        mock_adapter = AsyncMock()
        mock_adapter.complete = AsyncMock(side_effect=Exception("Adapter error"))

        with (
            patch(
                f"{_TOKEN_COUNTER}.count_message_tokens",
                return_value=80_000,
            ),
            patch(
                f"{_TOKEN_COUNTER}.get_context_limit",
                return_value=100_000,
            ),
            patch(
                f"{_ADAPTER_REGISTRY}.get_adapter",
                return_value=mock_adapter,
            ),
        ):
            result, compacted = await maybe_compact_context(messages, "claude-sonnet-4-6")

        assert compacted is False
        assert result is messages

    @pytest.mark.asyncio
    async def test_custom_threshold_and_keep_recent(self):
        """Custom threshold_pct and keep_recent values work."""
        messages = _make_messages(30)

        mock_adapter_result = MagicMock()
        mock_adapter_result.content = "Short summary."
        mock_adapter = AsyncMock()
        mock_adapter.complete = AsyncMock(return_value=mock_adapter_result)

        with (
            patch(
                f"{_TOKEN_COUNTER}.count_message_tokens",
                side_effect=[60_000, 5_000],
            ),
            patch(
                f"{_TOKEN_COUNTER}.get_context_limit",
                return_value=100_000,
            ),
            patch(
                f"{_ADAPTER_REGISTRY}.get_adapter",
                return_value=mock_adapter,
            ),
        ):
            _result, compacted = await maybe_compact_context(
                messages, "claude-sonnet-4-6",
                keep_recent=3, threshold_pct=0.5,
            )

        assert compacted is True
