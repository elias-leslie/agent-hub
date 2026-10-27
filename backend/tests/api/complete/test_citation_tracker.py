"""Tests for citation tracker citation persistence."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.api.complete.citation_tracker import track_citations_with_metrics


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
                model_used="claude-sonnet-5-5",
            )

        assert cited == ["c37d31f2-df9c-4298-bb73-d63015d7f746"]
        mock_inline_tags.assert_awaited_once()
        mock_store_cite_event.assert_awaited_once_with(
            db,
            "session-123",
            ["c37d31f2-df9c-4298-bb73-d63015d7f746"],
            "chat",
            "claude-sonnet-5-5",
        )
        db.commit.assert_awaited_once()
        mock_record_metrics.assert_awaited_once_with(
            ["c37d31f2-df9c-4298-bb73-d63015d7f746"],
            "session-123",
            None,
            False,
        )
