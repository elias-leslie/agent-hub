"""Tests for redundancy detection module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.memory.redundancy import (
    _pick_survivor,
    find_and_consolidate_redundant,
    find_redundant_pairs,
)


class TestPickSurvivor:
    """Tests for _pick_survivor()."""

    def test_higher_score_wins(self) -> None:
        pair = {
            "id_a": "aaaa", "score_a": 0.8, "tier_a": "reference",
            "id_b": "bbbb", "score_b": 0.5, "tier_b": "reference",
            "pinned_a": False, "pinned_b": False,
        }
        survivor, subordinate = _pick_survivor(pair)
        assert survivor == "aaaa"
        assert subordinate == "bbbb"

    def test_higher_tier_wins_on_tie(self) -> None:
        pair = {
            "id_a": "aaaa", "score_a": 0.5, "tier_a": "mandate",
            "id_b": "bbbb", "score_b": 0.5, "tier_b": "reference",
            "pinned_a": False, "pinned_b": False,
        }
        survivor, _subordinate = _pick_survivor(pair)
        assert survivor == "aaaa"  # mandate > reference

    def test_default_picks_a(self) -> None:
        pair = {
            "id_a": "aaaa", "score_a": 0.5, "tier_a": "reference",
            "id_b": "bbbb", "score_b": 0.5, "tier_b": "reference",
            "pinned_a": False, "pinned_b": False,
        }
        survivor, _ = _pick_survivor(pair)
        assert survivor == "aaaa"


class TestFindRedundantPairs:
    """Tests for find_redundant_pairs()."""

    @pytest.mark.asyncio
    async def test_returns_pairs_above_threshold(self) -> None:
        mock_row = MagicMock()
        mock_row.id_a = "aaaa-uuid"
        mock_row.name_a = "Mem A"
        mock_row.tier_a = 1
        mock_row.score_a = 0.9
        mock_row.pinned_a = False
        mock_row.id_b = "bbbb-uuid"
        mock_row.name_b = "Mem B"
        mock_row.tier_b = 3
        mock_row.score_b = 0.5
        mock_row.pinned_b = False
        mock_row.similarity = 0.95

        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("app.services.memory.redundancy.async_session", return_value=mock_session):
            pairs = await find_redundant_pairs()

        assert len(pairs) == 1
        assert pairs[0]["similarity"] == 0.95
        assert pairs[0]["tier_a"] == "mandate"

    @pytest.mark.asyncio
    async def test_empty_when_no_duplicates(self) -> None:
        mock_result = MagicMock()
        mock_result.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("app.services.memory.redundancy.async_session", return_value=mock_session):
            pairs = await find_redundant_pairs()

        assert pairs == []


class TestFindAndConsolidateRedundant:
    """Tests for find_and_consolidate_redundant()."""

    @pytest.mark.asyncio
    async def test_consolidates_high_similarity(self) -> None:
        """Pairs >= 0.97 should be auto-consolidated."""
        mock_pair = {
            "id_a": "aaaa-uuid",
            "name_a": "Mem A",
            "tier_a": "mandate",
            "score_a": 0.9,
            "pinned_a": False,
            "id_b": "bbbb-uuid",
            "name_b": "Mem B",
            "tier_b": "reference",
            "score_b": 0.5,
            "pinned_b": False,
            "similarity": 0.98,
        }

        with (
            patch("app.services.memory.redundancy.find_redundant_pairs", new_callable=AsyncMock, return_value=[mock_pair]),
            patch("app.services.memory.redundancy._consolidate_pair", new_callable=AsyncMock) as mock_consolidate,
        ):
            result = await find_and_consolidate_redundant()

        assert result["consolidated"] == 1
        mock_consolidate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_suggests_medium_similarity(self) -> None:
        """Pairs 0.92-0.97 should only log suggestions."""
        mock_pair = {
            "id_a": "aaaa-uuid",
            "name_a": "Mem A",
            "tier_a": "reference",
            "score_a": 0.5,
            "pinned_a": False,
            "id_b": "bbbb-uuid",
            "name_b": "Mem B",
            "tier_b": "reference",
            "score_b": 0.5,
            "pinned_b": False,
            "similarity": 0.94,
        }

        with (
            patch("app.services.memory.redundancy.find_redundant_pairs", new_callable=AsyncMock, return_value=[mock_pair]),
            patch("app.services.memory.redundancy.log_tier_change", new_callable=AsyncMock),
            patch("app.services.memory.redundancy._consolidate_pair", new_callable=AsyncMock) as mock_consolidate,
        ):
            result = await find_and_consolidate_redundant()

        assert result["suggestions"] == 1
        assert result["consolidated"] == 0
        mock_consolidate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_never_consolidates_pinned(self) -> None:
        """Pinned memories should not be auto-consolidated even at >= 0.97."""
        mock_pair = {
            "id_a": "aaaa-uuid",
            "name_a": "Mem A",
            "tier_a": "mandate",
            "score_a": 0.9,
            "pinned_a": True,  # pinned!
            "id_b": "bbbb-uuid",
            "name_b": "Mem B",
            "tier_b": "reference",
            "score_b": 0.5,
            "pinned_b": False,
            "similarity": 0.99,
        }

        with (
            patch("app.services.memory.redundancy.find_redundant_pairs", new_callable=AsyncMock, return_value=[mock_pair]),
            patch("app.services.memory.redundancy.log_tier_change", new_callable=AsyncMock),
            patch("app.services.memory.redundancy._consolidate_pair", new_callable=AsyncMock) as mock_consolidate,
        ):
            result = await find_and_consolidate_redundant()

        assert result["consolidated"] == 0
        assert result["suggestions"] == 1
        mock_consolidate.assert_not_awaited()
