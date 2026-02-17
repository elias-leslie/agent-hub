"""Tests for memory helpfulness rating."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.memory.memory_rater import (
    _parse_ratings,
    rate_session_memories,
)


@pytest.mark.unit
class TestParseRatings:
    """Tests for LLM response parsing."""

    def test_parse_valid_ratings(self) -> None:
        """Parses well-formed rating lines."""
        text = "[abc12345] helpful\n[def67890] harmful\n[11223344] neutral"
        contents = {
            "abc12345-full-uuid": "content1",
            "def67890-full-uuid": "content2",
            "11223344-full-uuid": "content3",
        }
        result = _parse_ratings(text, contents)
        assert result == {
            "abc12345-full-uuid": "helpful",
            "def67890-full-uuid": "harmful",
            "11223344-full-uuid": "neutral",
        }

    def test_parse_ignores_invalid_lines(self) -> None:
        """Skips lines that don't match expected format."""
        text = "Some preamble\n[abc12345] helpful\n\n[unknown1] helpful"
        contents = {"abc12345-full-uuid": "content1"}
        result = _parse_ratings(text, contents)
        assert result == {"abc12345-full-uuid": "helpful"}

    def test_parse_ignores_invalid_ratings(self) -> None:
        """Skips lines with invalid rating values."""
        text = "[abc12345] excellent\n[def67890] helpful"
        contents = {
            "abc12345-full-uuid": "content1",
            "def67890-full-uuid": "content2",
        }
        result = _parse_ratings(text, contents)
        assert result == {"def67890-full-uuid": "helpful"}

    def test_parse_empty_response(self) -> None:
        """Returns empty dict for empty response."""
        result = _parse_ratings("", {"abc-uuid": "content"})
        assert result == {}


@pytest.mark.unit
class TestRateSessionMemories:
    """Tests for rate_session_memories function."""

    @pytest.mark.asyncio
    async def test_skips_when_too_few_memories(self) -> None:
        """Skips rating when loaded memories below threshold."""
        with patch(
            "app.services.memory.memory_rater.get_memories_loaded",
            new_callable=AsyncMock,
            return_value=["uuid-1"],
        ):
            result = await rate_session_memories("session-1", "transcript")

        assert result.memories_rated == 0
        assert result.helpful_count == 0

    @pytest.mark.asyncio
    async def test_rates_and_credits_memories(self) -> None:
        """Full flow: fetches, rates, credits helpful/harmful."""
        loaded = [f"uuid-{i}" for i in range(5)]
        contents = {uuid: f"content for {uuid}" for uuid in loaded}

        with (
            patch(
                "app.services.memory.memory_rater.get_memories_loaded",
                new_callable=AsyncMock,
                return_value=loaded,
            ),
            patch(
                "app.services.memory.memory_rater._fetch_memory_contents",
                new_callable=AsyncMock,
                return_value=contents,
            ),
            patch(
                "app.services.memory.memory_rater._rate_via_llm",
                new_callable=AsyncMock,
                return_value={
                    "uuid-0": "helpful",
                    "uuid-1": "helpful",
                    "uuid-2": "harmful",
                    "uuid-3": "neutral",
                    "uuid-4": "neutral",
                },
            ),
            patch(
                "app.services.memory.usage_tracker.track_helpful_batch",
                new_callable=AsyncMock,
            ) as mock_helpful,
            patch(
                "app.services.memory.usage_tracker.track_harmful_batch",
                new_callable=AsyncMock,
            ) as mock_harmful,
        ):
            result = await rate_session_memories("session-1", "transcript text")

        assert result.memories_rated == 5
        assert result.helpful_count == 2
        assert result.harmful_count == 1
        assert result.neutral_count == 2
        mock_helpful.assert_called_once_with(["uuid-0", "uuid-1"])
        mock_harmful.assert_called_once_with(["uuid-2"])

    @pytest.mark.asyncio
    async def test_handles_empty_memory_contents(self) -> None:
        """Returns zero counts when no content found in Neo4j."""
        loaded = [f"uuid-{i}" for i in range(5)]

        with (
            patch(
                "app.services.memory.memory_rater.get_memories_loaded",
                new_callable=AsyncMock,
                return_value=loaded,
            ),
            patch(
                "app.services.memory.memory_rater._fetch_memory_contents",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            result = await rate_session_memories("session-1", "transcript text")

        assert result.memories_rated == 0

    @pytest.mark.asyncio
    async def test_handles_llm_failure(self) -> None:
        """Returns zero counts when LLM call fails."""
        loaded = [f"uuid-{i}" for i in range(5)]
        contents = {uuid: f"content for {uuid}" for uuid in loaded}

        with (
            patch(
                "app.services.memory.memory_rater.get_memories_loaded",
                new_callable=AsyncMock,
                return_value=loaded,
            ),
            patch(
                "app.services.memory.memory_rater._fetch_memory_contents",
                new_callable=AsyncMock,
                return_value=contents,
            ),
            patch(
                "app.services.memory.memory_rater._rate_via_llm",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            result = await rate_session_memories("session-1", "transcript")

        assert result.memories_rated == 0
        assert result.helpful_count == 0
