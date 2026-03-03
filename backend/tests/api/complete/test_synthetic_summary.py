"""Tests for synthetic summary generation in citation_tracker."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.api.complete.citation_tracker import _ensure_synthetic_summary, _track_inline_tags


class TestEnsureSyntheticSummary:
    """Verify _ensure_synthetic_summary generates summaries from content."""

    @pytest.mark.asyncio
    async def test_generates_summary_from_short_content(self):
        """Short content is stored as-is."""
        with patch(
            "app.services.memory.summary_generator._store_summary_on_session",
            new_callable=AsyncMock,
        ) as mock_store:
            await _ensure_synthetic_summary("Hello, world!", "session-1")

            mock_store.assert_called_once()
            assert mock_store.call_args.kwargs["summary_oneliner"] == "Hello, world!"
            assert mock_store.call_args.kwargs["outcome"] == "completed"

    @pytest.mark.asyncio
    async def test_truncates_at_sentence_boundary(self):
        """Content with a sentence boundary under 120 chars is truncated there."""
        content = "The server is running normally. Here are the detailed metrics and logs for the past 24 hours."
        with patch(
            "app.services.memory.summary_generator._store_summary_on_session",
            new_callable=AsyncMock,
        ) as mock_store:
            await _ensure_synthetic_summary(content, "session-2")

            summary = mock_store.call_args.kwargs["summary_oneliner"]
            assert summary == "The server is running normally."

    @pytest.mark.asyncio
    async def test_truncates_long_content_with_ellipsis(self):
        """Content over 120 chars without early sentence boundary gets ellipsis."""
        content = "A" * 200
        with patch(
            "app.services.memory.summary_generator._store_summary_on_session",
            new_callable=AsyncMock,
        ) as mock_store:
            await _ensure_synthetic_summary(content, "session-3")

            summary = mock_store.call_args.kwargs["summary_oneliner"]
            assert summary.endswith("...")
            assert len(summary) <= 150  # _enforce_oneliner max

    @pytest.mark.asyncio
    async def test_skips_empty_content(self):
        """Empty content should not store a summary."""
        with patch(
            "app.services.memory.summary_generator._store_summary_on_session",
            new_callable=AsyncMock,
        ) as mock_store:
            await _ensure_synthetic_summary("", "session-4")
            mock_store.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_whitespace_only(self):
        """Whitespace-only content should not store a summary."""
        with patch(
            "app.services.memory.summary_generator._store_summary_on_session",
            new_callable=AsyncMock,
        ) as mock_store:
            await _ensure_synthetic_summary("   \n  ", "session-5")
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
            await _track_inline_tags(content, db, "session-6", "coder", "claude-sonnet-4-5")

            mock_synthetic.assert_called_once_with(content, "session-6")

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
            await _track_inline_tags(content, db, "session-7", "coder", "claude-sonnet-4-5")

            mock_synthetic.assert_not_called()
