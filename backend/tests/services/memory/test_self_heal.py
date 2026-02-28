"""Tests for self-healing module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.memory.self_heal import find_and_apply_self_heals


def _make_archived_mem(
    *,
    lifecycle_score: float | None = None,
    referenced_count: int = 0,
    last_accessed_at: datetime | None = None,
    superseded_by: object | None = None,
) -> MagicMock:
    mem = MagicMock()
    mem.id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    mem.tier = 4
    mem.status = "active"
    mem.pinned = False
    mem.lifecycle_score = lifecycle_score
    mem.referenced_count = referenced_count
    mem.last_accessed_at = last_accessed_at
    mem.superseded_by = superseded_by
    return mem


class TestFindAndApplySelfHeals:
    """Tests for find_and_apply_self_heals()."""

    @pytest.mark.asyncio
    async def test_heals_high_lifecycle_score(self) -> None:
        """Memory with lifecycle_score >= 0.55 should be healed."""
        mem = _make_archived_mem(lifecycle_score=0.60)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mem]
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with (
            patch("app.services.memory.self_heal.async_session", return_value=mock_session),
            patch("app.services.memory.self_heal.promote_episode", new_callable=AsyncMock, return_value=True) as mock_promote,
            patch("app.services.memory.self_heal.log_tier_change", new_callable=AsyncMock),
        ):
            result = await find_and_apply_self_heals()

        assert result["healed"] == 1
        mock_promote.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_heals_recent_references(self) -> None:
        """Memory with recent access and sufficient refs should be healed."""
        mem = _make_archived_mem(
            lifecycle_score=0.30,  # below threshold
            referenced_count=5,
            last_accessed_at=datetime.now(UTC) - timedelta(days=2),
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mem]
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with (
            patch("app.services.memory.self_heal.async_session", return_value=mock_session),
            patch("app.services.memory.self_heal.promote_episode", new_callable=AsyncMock, return_value=True),
            patch("app.services.memory.self_heal.log_tier_change", new_callable=AsyncMock),
        ):
            result = await find_and_apply_self_heals()

        assert result["healed"] == 1

    @pytest.mark.asyncio
    async def test_skips_low_score_no_recent(self) -> None:
        """Memory with low score and no recent access should be skipped."""
        mem = _make_archived_mem(lifecycle_score=0.20, referenced_count=0)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mem]
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with (
            patch("app.services.memory.self_heal.async_session", return_value=mock_session),
            patch("app.services.memory.self_heal.promote_episode", new_callable=AsyncMock) as mock_promote,
            patch("app.services.memory.self_heal.log_tier_change", new_callable=AsyncMock),
        ):
            result = await find_and_apply_self_heals()

        assert result["healed"] == 0
        assert result["skipped"] == 1
        mock_promote.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_superseded(self) -> None:
        """Memories with superseded_by should not appear (filtered by query)."""
        # The SQL query filters out superseded memories, so empty list
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("app.services.memory.self_heal.async_session", return_value=mock_session):
            result = await find_and_apply_self_heals()

        assert result["healed"] == 0
