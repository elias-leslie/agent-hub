"""Tests for lifecycle scoring engine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.memory.lifecycle_score import (
    TIER_CONFIGS,
    batch_update_lifecycle_scores,
    compute_lifecycle_score,
)

# ---------------------------------------------------------------------------
# compute_lifecycle_score unit tests
# ---------------------------------------------------------------------------

class TestComputeLifecycleScore:
    """Tests for compute_lifecycle_score()."""

    NOW = datetime(2026, 2, 28, 12, 0, 0, tzinfo=UTC)

    def _score(self, **overrides: object) -> float:
        defaults = {
            "tier": "reference",
            "loaded_count": 100,
            "referenced_count": 10,
            "helpful_count": 0,
            "harmful_count": 0,
            "created_at": self.NOW - timedelta(days=5),
            "last_accessed_at": self.NOW - timedelta(hours=1),
            "now": self.NOW,
        }
        defaults.update(overrides)
        return compute_lifecycle_score(**defaults)  # type: ignore[arg-type]

    def test_new_memory_gets_grace_boost(self) -> None:
        """A memory within grace period should score high."""
        score = self._score(
            created_at=self.NOW - timedelta(days=1),
            last_accessed_at=self.NOW,
        )
        # Within 7-day grace, recently accessed, 10% cite rate matches expected
        assert score > 0.7

    def test_old_unused_memory_scores_low(self) -> None:
        """A memory with no references after many loads should score low."""
        score = self._score(
            loaded_count=500,
            referenced_count=0,
            created_at=self.NOW - timedelta(days=90),
            last_accessed_at=self.NOW - timedelta(days=60),
        )
        assert score < 0.4

    def test_harmful_drags_score_down(self) -> None:
        """Harmful feedback should reduce the score."""
        baseline = self._score(helpful_count=0, harmful_count=0)
        harmful = self._score(helpful_count=0, harmful_count=10)
        assert harmful < baseline

    def test_helpful_boosts_score(self) -> None:
        """Helpful feedback should increase the score."""
        baseline = self._score(helpful_count=0, harmful_count=0)
        helpful = self._score(helpful_count=10, harmful_count=0)
        assert helpful > baseline

    def test_mandate_stickiness_higher_than_archive(self) -> None:
        """Mandates should score higher than archives with same stats."""
        mandate = self._score(tier="mandate")
        archive = self._score(tier="archive")
        assert mandate > archive

    def test_zero_loads_gets_full_citation_credit(self) -> None:
        """Memories with zero loads should get full citation credit."""
        score = self._score(loaded_count=0, referenced_count=0)
        # citation_rate component should be 1.0 (full credit)
        assert score > 0.5

    def test_temporal_decay_halves_at_half_life(self) -> None:
        """Score should drop when memory hasn't been accessed for half_life days."""
        recent = self._score(last_accessed_at=self.NOW)
        cfg = TIER_CONFIGS["reference"]
        at_half_life = self._score(
            last_accessed_at=self.NOW - timedelta(days=cfg.decay_half_life_days),
        )
        # The temporal decay component (weight 0.20) should be halved
        assert at_half_life < recent

    def test_score_range(self) -> None:
        """Score should stay in reasonable range."""
        # Perfect memory
        high = self._score(
            tier="mandate",
            loaded_count=100,
            referenced_count=100,
            helpful_count=50,
            harmful_count=0,
            created_at=self.NOW - timedelta(days=1),
            last_accessed_at=self.NOW,
        )
        assert 0 < high <= 1.5  # stickiness can push above 1.0

        # Worst memory
        low = self._score(
            tier="archive",
            loaded_count=1000,
            referenced_count=0,
            helpful_count=0,
            harmful_count=50,
            created_at=self.NOW - timedelta(days=365),
            last_accessed_at=self.NOW - timedelta(days=300),
        )
        assert low >= 0

    def test_grace_period_decays_after_period(self) -> None:
        """Grace boost should decay after grace period ends."""
        in_grace = self._score(created_at=self.NOW - timedelta(days=3))
        after_grace = self._score(created_at=self.NOW - timedelta(days=30))
        assert in_grace > after_grace


# ---------------------------------------------------------------------------
# TierLifecycleConfig sanity
# ---------------------------------------------------------------------------

class TestTierConfigs:
    """Verify tier config sanity."""

    def test_all_tiers_configured(self) -> None:
        for tier in ("mandate", "guardrail", "reference", "archive"):
            assert tier in TIER_CONFIGS

    def test_mandate_stickiest(self) -> None:
        assert TIER_CONFIGS["mandate"].stickiness > TIER_CONFIGS["archive"].stickiness

    def test_demotion_thresholds_ordered(self) -> None:
        """Mandates should be hardest to demote (lowest threshold)."""
        assert TIER_CONFIGS["mandate"].demotion_threshold < TIER_CONFIGS["reference"].demotion_threshold

    def test_promotion_thresholds_ordered(self) -> None:
        """Mandates should be hardest to promote into (highest threshold)."""
        assert TIER_CONFIGS["mandate"].promotion_threshold > TIER_CONFIGS["archive"].promotion_threshold


# ---------------------------------------------------------------------------
# batch_update_lifecycle_scores
# ---------------------------------------------------------------------------

class TestBatchUpdateLifecycleScores:
    """Tests for batch_update_lifecycle_scores()."""

    @pytest.mark.asyncio
    async def test_batch_updates_all_active(self) -> None:
        """Should update lifecycle_score for all active memories."""
        mock_mem = MagicMock()
        mock_mem.id = "fake-uuid"
        mock_mem.tier = 1
        mock_mem.loaded_count = 100
        mock_mem.referenced_count = 20
        mock_mem.helpful_count = 5
        mock_mem.harmful_count = 0
        mock_mem.created_at = datetime.now(UTC) - timedelta(days=10)
        mock_mem.last_accessed_at = datetime.now(UTC)
        mock_mem.status = "active"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_mem]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("app.services.memory.lifecycle_score.async_session", return_value=mock_session):
            result = await batch_update_lifecycle_scores()

        assert result["updated"] == 1
        assert "mandate" in result["by_tier"]
        assert result["by_tier"]["mandate"]["count"] == 1
        # execute called: 1 for SELECT + 1 for UPDATE
        assert mock_session.execute.call_count == 2
        mock_session.commit.assert_awaited_once()
