"""Tests for stable memory pagination cursors."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.memory._repo_query import (
    QueryRepository,
    _build_pagination_cursor,
    _parse_pagination_cursor,
)


def test_pagination_cursor_round_trips_with_uuid_tiebreaker() -> None:
    """Composite cursors should preserve both timestamp and UUID."""
    created_at = datetime(2026, 3, 9, 20, 0, 0, tzinfo=UTC)
    memory_id = uuid4()

    cursor = _build_pagination_cursor(created_at, memory_id)
    parsed_at, parsed_id = _parse_pagination_cursor(cursor)

    assert parsed_at == created_at
    assert parsed_id == memory_id


@pytest.mark.asyncio
async def test_list_paginated_uses_uuid_tiebreaker_when_cursor_contains_uuid() -> None:
    """Cursor filtering should avoid skipping equal-timestamp rows across pages."""
    repo = QueryRepository()
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result.scalars.return_value = mock_scalars
    mock_db.execute.return_value = mock_result

    created_at = datetime(2026, 3, 9, 20, 0, 0, tzinfo=UTC)
    memory_id = uuid4()
    cursor = _build_pagination_cursor(created_at, memory_id)

    await repo.list_paginated(limit=25, cursor=cursor, db=mock_db)

    stmt = mock_db.execute.call_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    assert "ORDER BY memories.updated_at DESC, memories.id DESC" in compiled
    assert "memories.updated_at = " in compiled
    assert f"memories.id < '{str(memory_id).replace('-', '')}'" in compiled


@pytest.mark.asyncio
async def test_list_paginated_created_at_sort_uses_created_at_column() -> None:
    """Explicit created_at sorting should keep the historical ordering path."""
    repo = QueryRepository()
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result.scalars.return_value = mock_scalars
    mock_db.execute.return_value = mock_result

    await repo.list_paginated(limit=10, order_by="created_at", sort_order="asc", db=mock_db)

    stmt = mock_db.execute.call_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    assert "ORDER BY memories.created_at ASC, memories.id ASC" in compiled


@pytest.mark.asyncio
async def test_list_by_scope_and_tier_supports_uncapped_policy_retrieval() -> None:
    """Required policy retrieval must not silently stop at the generic page size."""
    repo = QueryRepository()
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = mock_result

    await repo.list_by_scope_and_tier(tier="mandate", limit=None, db=mock_db)

    stmt = mock_db.execute.call_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert " LIMIT " not in compiled


def test_parse_pagination_cursor_accepts_legacy_timestamp_only() -> None:
    """Older cursor values should remain valid for backward compatibility."""
    created_at = datetime(2026, 3, 9, 20, 0, 0, tzinfo=UTC)

    parsed_at, parsed_id = _parse_pagination_cursor(created_at.isoformat())

    assert parsed_at == created_at
    assert parsed_id is None
