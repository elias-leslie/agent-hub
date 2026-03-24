"""Tests for synthetic summary generation in citation_tracker."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.api.complete.citation_tracker import (
    _ensure_synthetic_summary,
    _extract_chat_summary,
    _track_inline_tags,
)
from app.constants.models import CLAUDE_SONNET

# Matches the 120-char truncation in _extract_chat_summary
MAX_SUMMARY_LENGTH = 120


class TestExtractChatSummary:
    """Unit tests for _extract_chat_summary."""

    def test_extract_chat_summary_short_content_returns_unchanged(self):
        assert _extract_chat_summary("Hello, world!") == "Hello, world!"

    def test_extract_chat_summary_sentence_boundary_truncates_at_sentence(self):
        content = "The server is running normally. Here are the detailed metrics."
        assert _extract_chat_summary(content) == "The server is running normally."

    def test_extract_chat_summary_long_content_appends_ellipsis(self):
        summary = _extract_chat_summary("A" * 200)
        assert summary.endswith("...")
        # MAX_SUMMARY_LENGTH (120) + ellipsis (3) = max output length
        assert len(summary) <= MAX_SUMMARY_LENGTH + len("...")

    def test_extract_chat_summary_empty_content_returns_empty(self):
        assert _extract_chat_summary("") == ""

    def test_extract_chat_summary_whitespace_only_returns_empty(self):
        assert _extract_chat_summary("   \n  ") == ""

    def test_extract_chat_summary_no_transformation_returns_same_content(self):
        """Content is taken as-is — no filtering, no special handling."""
        summary = _extract_chat_summary("Sure! The database has 42 tables in it.")
        assert summary == "The database has 42 tables in it."

    def test_extract_chat_summary_ignores_command_tail(self):
        content = (
            "[[P:tested:dt -q -d passes clean - biome OK, tsc OK, zero errors]] "
            "Type checks pass. Now commit via `/commit_it`."
        )

        summary = _extract_chat_summary(content)

        assert "/commit_it" not in summary
        assert "passes clean" in summary or "Type checks pass." in summary


class TestEnsureSyntheticSummary:
    """Verify _ensure_synthetic_summary stores summaries via _store_summary_on_session."""

    @pytest.mark.asyncio
    async def test_stores_summary(self):
        db = AsyncMock()

        with patch(
            "app.services.memory.summary_generator._store_summary_on_session",
            new_callable=AsyncMock,
        ) as mock_store:
            stored = await _ensure_synthetic_summary("The server is healthy.", "session-1", db=db)

            assert stored is True
            mock_store.assert_called_once()
            assert mock_store.call_args.kwargs["summary_oneliner"] == "The server is healthy."
            assert mock_store.call_args.kwargs["outcome"] == "completed"
            assert mock_store.call_args.kwargs["db"] is db

    @pytest.mark.asyncio
    async def test_skips_empty_content(self):
        with patch(
            "app.services.memory.summary_generator._store_summary_on_session",
            new_callable=AsyncMock,
        ) as mock_store:
            stored = await _ensure_synthetic_summary("", "session-2")
            assert stored is False
            mock_store.assert_not_called()


class TestTrackInlineTagsSyntheticFallback:
    """Verify _track_inline_tags generates synthetic summary when no [[S:...]] tags."""

    @pytest.mark.asyncio
    async def test_generates_synthetic_when_no_summary_tags(self):
        """When no [[S:...]] tags, a synthetic summary is generated."""
        content = "Here is the analysis of the codebase."
        db = AsyncMock()

        with (
            patch(
                "app.api.complete.citation_tracker.track_inline_feedback",
                new_callable=AsyncMock,
            ),
            patch(
                "app.api.complete.citation_tracker.track_inline_summaries",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.api.complete.citation_tracker._ensure_synthetic_summary",
                new_callable=AsyncMock,
            ) as mock_synthetic,
        ):
            await _track_inline_tags(content, db, "session-6", "coder", CLAUDE_SONNET)

            mock_synthetic.assert_called_once_with(content, "session-6", db=db)

    @pytest.mark.asyncio
    async def test_skips_synthetic_when_inline_summary_found(self):
        """When [[S:...]] tags found, no synthetic summary is generated."""
        content = "Done. [[S:completed:Fixed the bug]]"
        db = AsyncMock()

        with (
            patch(
                "app.api.complete.citation_tracker.track_inline_feedback",
                new_callable=AsyncMock,
            ),
            patch(
                "app.api.complete.citation_tracker.track_inline_summaries",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.api.complete.citation_tracker._ensure_synthetic_summary",
                new_callable=AsyncMock,
            ) as mock_synthetic,
        ):
            await _track_inline_tags(content, db, "session-7", "coder", CLAUDE_SONNET)

            mock_synthetic.assert_not_called()
