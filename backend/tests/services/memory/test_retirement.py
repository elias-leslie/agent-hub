"""Tests for graduated retirement pipeline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.memory.retirement import retire_stale_archives


def _make_stale_mem(days_old: int = 200) -> MagicMock:
    mem = MagicMock()
    mem.id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    mem.tier = 4
    mem.status = "active"
    mem.pinned = False
    mem.superseded_by = None
    mem.last_accessed_at = None
    mem.created_at = datetime.now(UTC) - timedelta(days=days_old)
    return mem


class TestRetireStaleArchives:
    """Tests for retire_stale_archives()."""

    @pytest.mark.asyncio
    async def test_retires_stale_archive(self) -> None:
        """Archives untouched for >180 days should be retired."""
        stale = _make_stale_mem(days_old=200)

        mock_last_result = MagicMock()
        mock_last_result.scalar.return_value = datetime.now(UTC)  # system is active

        mock_stale_result = MagicMock()
        mock_stale_result.scalars.return_value.all.return_value = [stale]

        mock_update_result = MagicMock()

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_last_result
            if call_count == 2:
                return mock_stale_result
            return mock_update_result

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=mock_execute)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("app.services.memory.retirement.async_session", return_value=mock_session):
            result = await retire_stale_archives()

        assert result["retired"] == 1
        assert result["skipped"] is False

    @pytest.mark.asyncio
    async def test_skips_inactive_system(self) -> None:
        """If system is inactive (no recent active memories), skip retirement."""
        mock_last_result = MagicMock()
        # Last active memory created 200 days ago — system looks inactive
        mock_last_result.scalar.return_value = datetime.now(UTC) - timedelta(days=200)

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_last_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("app.services.memory.retirement.async_session", return_value=mock_session):
            result = await retire_stale_archives()

        assert result["retired"] == 0
        assert result["skipped"] is True

    @pytest.mark.asyncio
    async def test_no_stale_archives(self) -> None:
        """Returns zero retired when no stale archives exist."""
        mock_last_result = MagicMock()
        mock_last_result.scalar.return_value = datetime.now(UTC)

        mock_stale_result = MagicMock()
        mock_stale_result.scalars.return_value.all.return_value = []

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_last_result
            return mock_stale_result

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=mock_execute)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("app.services.memory.retirement.async_session", return_value=mock_session):
            result = await retire_stale_archives()

        assert result["retired"] == 0
        assert result["skipped"] is False
