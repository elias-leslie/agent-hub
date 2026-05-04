from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.session_queries import query_session_events


@pytest.mark.asyncio
async def test_query_session_events_returns_max_turn_not_total_pages() -> None:
    db = AsyncMock()

    count_result = MagicMock()
    count_result.scalar.return_value = 5

    max_turn_result = MagicMock()
    max_turn_result.scalar.return_value = 2

    events_result = MagicMock()
    events_result.scalars.return_value.all.return_value = []

    db.execute = AsyncMock(side_effect=[count_result, max_turn_result, events_result])

    events, total, max_turn = await query_session_events(
        db,
        "session-1",
        page=1,
        page_size=2,
    )

    assert events == []
    assert total == 5
    assert max_turn == 2
