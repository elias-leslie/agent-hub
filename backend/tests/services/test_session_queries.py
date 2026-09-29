from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.session_queries import encode_session_event_snapshot, query_session_events


@pytest.mark.asyncio
async def test_query_session_events_returns_max_turn_not_total_pages() -> None:
    db = AsyncMock()

    snapshot_result = MagicMock()
    snapshot_result.one_or_none.return_value = (
        datetime(2026, 9, 29, 15, 0, tzinfo=UTC),
        "10000000-0000-0000-0000-000000000005",
    )

    count_result = MagicMock()
    count_result.scalar.return_value = 5

    max_turn_result = MagicMock()
    max_turn_result.scalar.return_value = 2

    events_result = MagicMock()
    events_result.scalars.return_value.all.return_value = []

    db.execute = AsyncMock(
        side_effect=[snapshot_result, count_result, max_turn_result, events_result]
    )

    events, total, max_turn, snapshot = await query_session_events(
        db,
        "session-1",
        page=1,
        page_size=2,
    )

    assert events == []
    assert total == 5
    assert max_turn == 2
    assert snapshot == encode_session_event_snapshot(
        datetime(2026, 9, 29, 15, 0, tzinfo=UTC),
        "10000000-0000-0000-0000-000000000005",
    )


@pytest.mark.asyncio
async def test_query_session_events_reuses_fixed_snapshot_without_reanchoring() -> None:
    db = AsyncMock()
    count_result = MagicMock()
    count_result.scalar.return_value = 2
    max_turn_result = MagicMock()
    max_turn_result.scalar.return_value = 1
    events_result = MagicMock()
    events_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(side_effect=[count_result, max_turn_result, events_result])
    snapshot = encode_session_event_snapshot(
        datetime(2026, 9, 29, 15, 0, tzinfo=UTC),
        "10000000-0000-0000-0000-000000000002",
    )

    events, total, max_turn, returned_snapshot = await query_session_events(
        db,
        "session-1",
        page=2,
        page_size=1,
        snapshot=snapshot,
    )

    assert events == []
    assert total == 2
    assert max_turn == 1
    assert returned_snapshot == snapshot
    assert db.execute.await_count == 3
