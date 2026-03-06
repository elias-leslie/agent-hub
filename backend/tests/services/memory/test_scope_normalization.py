"""Tests for legacy memory scope normalization."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.memory.scope_normalization import normalize_legacy_scope_rows


@pytest.mark.asyncio
async def test_normalize_legacy_scope_rows_returns_rowcounts() -> None:
    """Normalization should commit and report per-query row counts."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.execute = AsyncMock(
        side_effect=[
            MagicMock(rowcount=2),
            MagicMock(rowcount=5),
            MagicMock(rowcount=1),
        ]
    )

    with patch(
        "app.services.memory.scope_normalization.async_session",
        return_value=mock_session,
    ):
        result = await normalize_legacy_scope_rows()

    assert result == {
        "legacy_prefixed_scope": 2,
        "global_scope_project_group": 5,
        "project_scope_missing_scope_id": 1,
    }
    assert mock_session.execute.await_count == 3
    mock_session.commit.assert_awaited_once()

