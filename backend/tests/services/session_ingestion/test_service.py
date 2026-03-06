"""Tests for the canonical session ingestion service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.session_ingestion.models import (
    AppendNormalizedEventsRequest,
    NormalizedEvent,
)
from app.services.session_ingestion.service import append_normalized_events


@pytest.mark.unit
@pytest.mark.asyncio
async def test_append_normalized_events_skips_existing_turn_sequence_pair() -> None:
    db = AsyncMock()

    existing_pairs = MagicMock()
    existing_pairs.all.return_value = [(1, 1)]
    db.execute = AsyncMock(return_value=existing_pairs)

    stored_event = MagicMock()
    stored_event.id = "evt-2"

    with (
        patch(
            "app.services.session_ingestion.service.get_max_turn",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch(
            "app.services.session_ingestion.service.get_max_sequence",
            new_callable=AsyncMock,
            return_value=1,
        ),
        patch(
            "app.services.session_ingestion.service.store_event",
            new_callable=AsyncMock,
            return_value=stored_event,
        ) as mock_store,
    ):
        result = await append_normalized_events(
            db=db,
            session_id="session-123",
            request=AppendNormalizedEventsRequest(
                events=[
                    NormalizedEvent(
                        event_type="assistant_message",
                        turn=1,
                        sequence=1,
                        role="assistant",
                        content="existing",
                    ),
                    NormalizedEvent(
                        event_type="assistant_message",
                        turn=1,
                        sequence=2,
                        role="assistant",
                        content="new",
                    ),
                ]
            ),
        )

    assert result.events_appended == 1
    assert result.events_skipped == 1
    assert result.event_ids == ["evt-2"]
    mock_store.assert_awaited_once()
