"""Tests for citation tracker feedback and citation persistence."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.complete.citation_tracker import (
    track_citations_with_metrics,
    track_inline_feedback,
)


@pytest.mark.unit
class TestTrackInlineFeedback:
    """Tests for track_inline_feedback function."""

    @pytest.mark.asyncio
    async def test_track_inline_feedback_creates_items(self):
        """Feedback tags are parsed and create_feedback_item is called."""
        content = "[F:friction:sf.cli] bad error message"
        db = AsyncMock()
        # Mock the project_id query
        project_row = MagicMock()
        project_row.scalar_one_or_none.return_value = "summitflow"
        db.execute = AsyncMock(side_effect=[
            project_row,   # Session.project_id query
            MagicMock(  # existing feedback query (empty)
                __iter__=lambda self: iter([])
            ),
        ])

        with patch(
            "app.services.feedback_storage.create_feedback_item",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = MagicMock()
            count = await track_inline_feedback(
                content, db, "session-123",
                agent_id="coder", model_used="claude-opus-4-6",
            )

        assert count == 1
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args
        assert call_kwargs.kwargs["component_id"] == "sf.cli"
        assert call_kwargs.kwargs["feedback_type"] == "friction"
        assert call_kwargs.kwargs["session_type"] == "inline_tag"

    @pytest.mark.asyncio
    async def test_track_inline_feedback_dedup_same_session(self):
        """Same (component, type) tag twice in one session creates only one item."""
        content = (
            "[F:friction:sf.cli] first complaint\n"
            "[F:friction:sf.cli] second complaint same component"
        )
        db = AsyncMock()
        project_row = MagicMock()
        project_row.scalar_one_or_none.return_value = "summitflow"

        # First execute returns project_id, second returns existing feedback (empty)
        db.execute = AsyncMock(side_effect=[
            project_row,
            MagicMock(__iter__=lambda self: iter([])),
        ])

        with patch(
            "app.services.feedback_storage.create_feedback_item",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = MagicMock()
            count = await track_inline_feedback(
                content, db, "session-123",
            )

        # Only one call since both tags have the same (component_id, feedback_type)
        assert count == 1
        assert mock_create.call_count == 1

    @pytest.mark.asyncio
    async def test_track_inline_feedback_no_tags(self):
        """No feedback tags returns 0 without DB queries."""
        content = "Just normal text with [M:abc12345] citation"
        db = AsyncMock()

        count = await track_inline_feedback(content, db, "session-123")

        assert count == 0
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_track_inline_feedback_skips_existing(self):
        """Tags already stored for session are skipped."""
        content = "[F:friction:sf.cli] bad error message"
        db = AsyncMock()
        project_row = MagicMock()
        project_row.scalar_one_or_none.return_value = "summitflow"

        # Simulate existing feedback row matching this tag
        existing_row = MagicMock()
        existing_row.component_id = "sf.cli"
        existing_row.feedback_type = "friction"

        db.execute = AsyncMock(side_effect=[
            project_row,
            MagicMock(__iter__=lambda self: iter([existing_row])),
        ])

        with patch(
            "app.services.feedback_storage.create_feedback_item",
            new_callable=AsyncMock,
        ) as mock_create:
            count = await track_inline_feedback(content, db, "session-123")

        assert count == 0
        mock_create.assert_not_called()


@pytest.mark.unit
class TestTrackCitationsWithMetrics:
    """Tests for completion citation tracking with DB persistence."""

    @pytest.mark.asyncio
    async def test_track_citations_with_metrics_stores_cite_event_when_db_present(self) -> None:
        """Native completion should persist memory_cite events when DB is available."""
        db = AsyncMock()

        with (
            patch(
                "app.api.complete.citation_tracker._track_inline_tags",
                new_callable=AsyncMock,
            ) as mock_inline_tags,
            patch(
                "app.api.complete.citation_tracker._resolve_cited_uuids",
                new_callable=AsyncMock,
                return_value=["c37d31f2-df9c-4298-bb73-d63015d7f746"],
            ),
            patch(
                "app.api.complete.citation_tracker._store_cite_event",
                new_callable=AsyncMock,
            ) as mock_store_cite_event,
            patch(
                "app.api.complete.citation_tracker._record_citation_metrics",
                new_callable=AsyncMock,
            ) as mock_record_metrics,
        ):
            cited = await track_citations_with_metrics(
                content="Applied: [M:c37d31f2]",
                loaded_memory_uuids=["c37d31f2-df9c-4298-bb73-d63015d7f746"],
                memory_group_id=None,
                session_id="session-123",
                external_id=None,
                is_error=False,
                db=db,
                agent_id="chat",
                model_used="claude-sonnet-4-6",
            )

        assert cited == ["c37d31f2-df9c-4298-bb73-d63015d7f746"]
        mock_inline_tags.assert_awaited_once()
        mock_store_cite_event.assert_awaited_once_with(
            db,
            "session-123",
            ["c37d31f2-df9c-4298-bb73-d63015d7f746"],
            "chat",
            "claude-sonnet-4-6",
        )
        db.commit.assert_awaited_once()
        mock_record_metrics.assert_awaited_once_with(
            ["c37d31f2-df9c-4298-bb73-d63015d7f746"],
            "session-123",
            None,
            False,
        )
