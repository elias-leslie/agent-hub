"""Tests for memory tier lifecycle — demotion, promotion, and hierarchy navigation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.memory._repo_helpers import TIER_MAP, TIER_REVERSE
from app.services.memory.tier_operations import (
    TIER_HIERARCHY,
    get_next_tier_down,
    get_next_tier_up,
)


class TestTierHierarchy:
    """Tests for TIER_HIERARCHY navigation."""

    def test_hierarchy_includes_archive(self):
        """archive must be in the hierarchy for tier-3 demotion to work."""
        assert "archive" in TIER_HIERARCHY
        assert TIER_HIERARCHY == ["mandate", "guardrail", "reference", "archive"]

    def test_get_next_tier_down_mandate(self):
        assert get_next_tier_down("mandate") == "guardrail"

    def test_get_next_tier_down_guardrail(self):
        assert get_next_tier_down("guardrail") == "reference"

    def test_get_next_tier_down_reference(self):
        """reference must demote to archive, not return None."""
        assert get_next_tier_down("reference") == "archive"

    def test_get_next_tier_down_archive(self):
        """archive is the bottom — no further demotion."""
        assert get_next_tier_down("archive") is None

    def test_get_next_tier_down_unknown(self):
        assert get_next_tier_down("nonexistent") is None

    def test_get_next_tier_up_archive(self):
        assert get_next_tier_up("archive") == "reference"

    def test_get_next_tier_up_reference(self):
        assert get_next_tier_up("reference") == "guardrail"

    def test_get_next_tier_up_mandate(self):
        """mandate is the top — no further promotion."""
        assert get_next_tier_up("mandate") is None


class TestTierMap:
    """Tests for TIER_MAP and TIER_REVERSE consistency."""

    def test_tier_map_includes_archive(self):
        assert TIER_MAP["archive"] == 4

    def test_tier_reverse_includes_4(self):
        assert TIER_REVERSE[4] == "archive"

    def test_tier_map_complete(self):
        assert TIER_MAP == {"mandate": 1, "guardrail": 2, "reference": 3, "archive": 4}


class TestDemotionCandidates:
    """Tests for find_demotion_candidates including tier-3 memories."""

    @pytest.mark.asyncio
    async def test_tier3_memories_included_in_demotion_candidates(self):
        """Tier-3 (reference) memories must be visible to the demotion query."""
        from app.services.memory._repo_tier import TierRepository

        repo = TierRepository()

        # Create mock tier-3 memory with high ghost ratio
        mock_mem = MagicMock()
        mock_mem.id = uuid4()
        mock_mem.name = "dead-weight-ref"
        mock_mem.injection_tier = "reference"
        mock_mem.tier = 3
        mock_mem.status = "active"
        mock_mem.pinned = False
        mock_mem.loaded_count = 250
        mock_mem.referenced_count = 0
        mock_mem.helpful_count = 0
        mock_mem.harmful_count = 0
        mock_mem.utility_score = 0.01
        mock_mem.created_at = datetime.now(UTC) - timedelta(days=30)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_mem]
        mock_db.execute.return_value = mock_result

        candidates = await repo.find_demotion_candidates(db=mock_db)

        assert len(candidates) == 1
        assert candidates[0]["name"] == "dead-weight-ref"
        assert candidates[0]["injection_tier"] == "reference"

        # Verify the query included tier 3
        call_args = mock_db.execute.call_args
        stmt = call_args[0][0]
        # The statement should have been constructed with tier.in_([1, 2, 3])
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "3" in compiled
