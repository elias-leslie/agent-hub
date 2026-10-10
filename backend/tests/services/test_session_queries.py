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


def test_benchmark_exclusion_mirrors_attribution_metadata_rule() -> None:
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    from app.models import Session
    from app.services.session_queries import SessionListFilters, session_list_predicates

    predicates = session_list_predicates(SessionListFilters(exclude_benchmarks=True))
    sql = str(select(Session.id).where(*predicates).compile(dialect=postgresql.dialect()))
    assert "sessions.provider_metadata ->> " in sql
    assert "NOT coalesce" in sql


def test_title_collapses_whitespace_and_caps_length() -> None:
    from app.services.session_queries import normalize_session_title

    assert normalize_session_title("  a \n\t b  ") == "a b"
    assert normalize_session_title("   ") is None
    assert normalize_session_title(None) is None
    assert len(normalize_session_title("y" * 500) or "") == 160


def test_event_cursor_encodes_order_turn_and_sequence() -> None:
    from app.services.session_queries import (
        decode_session_event_cursor,
        encode_session_event_cursor,
    )

    cursor = encode_session_event_cursor("desc", 7, 3)
    assert decode_session_event_cursor(cursor, "desc") == (7, 3)
    with pytest.raises(ValueError, match="order"):
        decode_session_event_cursor(cursor, "asc")
    with pytest.raises(ValueError, match="Invalid"):
        decode_session_event_cursor("bad", "asc")
