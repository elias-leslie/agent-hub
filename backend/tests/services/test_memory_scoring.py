"""Tests for multi-factor memory scoring (ac-003, ac-006 verification)."""

from datetime import UTC, datetime, timedelta

from app.services.memory.scoring import (
    MemoryScore,
    MemoryScoreInput,
    calculate_recency_decay,
    calculate_usage_effectiveness,
    rank_memories,
    score_memory,
)
from app.services.memory.variants import BASELINE_CONFIG, MINIMAL_CONFIG


class TestCalculateRecencyDecay:
    """Tests for recency decay calculation."""

    def test_fresh_item_full_score(self):
        """Test item created just now gets full score."""
        now = datetime.now(UTC)
        created = now - timedelta(minutes=5)

        score = calculate_recency_decay(created, None, half_life_days=30, now=now)
        assert score > 0.99

    def test_half_life_decay(self):
        """Test item at half-life gets ~0.5 score."""
        now = datetime.now(UTC)
        created = now - timedelta(days=30)

        score = calculate_recency_decay(created, None, half_life_days=30, now=now)
        assert 0.49 <= score <= 0.51

    def test_old_item_low_score(self):
        """Test very old item gets low score."""
        now = datetime.now(UTC)
        created = now - timedelta(days=180)  # 6 months

        score = calculate_recency_decay(created, None, half_life_days=30, now=now)
        assert score < 0.1

    def test_uses_more_recent_timestamp(self):
        """Test uses more recent of created_at or last_used_at."""
        now = datetime.now(UTC)
        created = now - timedelta(days=60)  # Old
        last_used = now - timedelta(days=1)  # Recent

        score = calculate_recency_decay(created, last_used, half_life_days=30, now=now)
        # Should use last_used (1 day ago), not created (60 days ago)
        assert score > 0.9

    def test_no_timestamps_returns_default(self):
        """Test missing timestamps return 0.5 default."""
        score = calculate_recency_decay(None, None, half_life_days=30)
        assert score == 0.5

    def test_different_half_lives(self):
        """Test different half-lives produce different decay rates."""
        now = datetime.now(UTC)
        created = now - timedelta(days=14)

        # 7-day half-life (2 half-lives passed)
        score_7 = calculate_recency_decay(created, None, half_life_days=7, now=now)

        # 30-day half-life (less than 1 half-life)
        score_30 = calculate_recency_decay(created, None, half_life_days=30, now=now)

        # Shorter half-life should decay faster
        assert score_7 < score_30


class TestCalculateUsageEffectiveness:
    """Tests for usage effectiveness calculation."""

    def test_never_loaded_returns_baseline(self):
        """Test never-loaded item gets 0.5 baseline."""
        score = calculate_usage_effectiveness(loaded_count=0, referenced_count=0)
        assert score == 0.5

    def test_always_referenced_full_score(self):
        """Test always-referenced item gets 1.0."""
        score = calculate_usage_effectiveness(loaded_count=10, referenced_count=10)
        assert score == 1.0

    def test_never_referenced_zero_score(self):
        """Test never-referenced item gets 0.0."""
        score = calculate_usage_effectiveness(loaded_count=10, referenced_count=0)
        assert score == 0.0

    def test_partial_reference_rate(self):
        """Test partial reference rate."""
        score = calculate_usage_effectiveness(loaded_count=10, referenced_count=5)
        assert score == 0.5

    def test_capped_at_one(self):
        """Test score is capped at 1.0 even with over-referencing."""
        score = calculate_usage_effectiveness(loaded_count=5, referenced_count=10)
        assert score == 1.0


class TestScoreMemory:
    """Tests for score_memory function."""

    def test_scores_between_zero_and_one_base(self):
        """Test base score (before multipliers) is between 0 and 1."""
        input_data = MemoryScoreInput(
            semantic_similarity=0.8,
            confidence=80.0,
            loaded_count=10,
            referenced_count=5,
            created_at=datetime.now(UTC),
            tier="reference",
        )

        result = score_memory(input_data, BASELINE_CONFIG)

        # Components should be 0-1
        assert 0 <= result.semantic_component <= 1
        assert 0 <= result.usage_component <= 1
        assert 0 <= result.confidence_component <= 1
        assert 0 <= result.recency_component <= 1

    def test_weights_sum_correctly(self):
        """Test weight distribution is applied correctly (ac-003)."""
        input_data = MemoryScoreInput(
            semantic_similarity=1.0,  # Max semantic
            confidence=100.0,  # Max confidence
            loaded_count=10,
            referenced_count=10,  # Max usage
            created_at=datetime.now(UTC),  # Fresh (max recency)
            tier="reference",
        )

        result = score_memory(input_data, BASELINE_CONFIG)

        # With all max values and reference tier (1.0 multiplier):
        # semantic=1.0*0.4 + usage=1.0*0.3 + confidence=1.0*0.2 + recency≈1.0*0.1 = ~1.0
        # (reference tier has 1.0 multiplier, so final ≈ 1.0)
        assert 0.95 <= result.final_score <= 1.05

    def test_mandate_tier_multiplier(self):
        """Test mandate tier gets higher multiplier."""
        base_input = MemoryScoreInput(
            semantic_similarity=0.7,
            confidence=70.0,
            tier="reference",
        )
        mandate_input = MemoryScoreInput(
            semantic_similarity=0.7,
            confidence=70.0,
            tier="mandate",
        )

        ref_score = score_memory(base_input, BASELINE_CONFIG)
        mandate_score = score_memory(mandate_input, BASELINE_CONFIG)

        # Mandate should have higher score due to tier multiplier
        assert mandate_score.final_score > ref_score.final_score
        assert mandate_score.tier_multiplier == 2.0

    def test_tag_boost_applied(self):
        """Test tag match provides score boost."""
        no_tag = MemoryScoreInput(
            semantic_similarity=0.7,
            confidence=70.0,
            has_tag_match=False,
        )
        with_tag = MemoryScoreInput(
            semantic_similarity=0.7,
            confidence=70.0,
            has_tag_match=True,
        )

        no_tag_score = score_memory(no_tag, BASELINE_CONFIG)
        with_tag_score = score_memory(with_tag, BASELINE_CONFIG)

        assert with_tag_score.final_score > no_tag_score.final_score
        assert with_tag_score.tag_boost == 1.3

    def test_threshold_check(self):
        """Test passes_threshold is computed correctly."""
        high_score_input = MemoryScoreInput(
            semantic_similarity=0.9,
            confidence=90.0,
            tier="mandate",
        )
        low_score_input = MemoryScoreInput(
            semantic_similarity=0.1,
            confidence=10.0,
            tier="reference",
        )

        high = score_memory(high_score_input, BASELINE_CONFIG)
        low = score_memory(low_score_input, BASELINE_CONFIG)

        assert high.passes_threshold is True
        assert low.passes_threshold is False

    def test_variant_config_affects_scoring(self):
        """Test different variants produce different scores."""
        input_data = MemoryScoreInput(
            semantic_similarity=0.6,
            confidence=60.0,
        )

        baseline = score_memory(input_data, BASELINE_CONFIG)
        minimal = score_memory(input_data, MINIMAL_CONFIG)

        # MINIMAL has higher threshold, so might not pass
        # and different weight distribution
        assert baseline.final_score != minimal.final_score


class TestRankMemories:
    """Tests for rank_memories function."""

    def test_ranks_by_score_descending(self):
        """Test memories are ranked highest score first."""
        memories = [
            ("low", MemoryScore(0.3, 0.3, 0.3, 0.3, 0.3, 1.0, 1.0, False)),
            ("high", MemoryScore(0.9, 0.9, 0.9, 0.9, 0.9, 1.0, 1.0, True)),
            ("mid", MemoryScore(0.6, 0.6, 0.6, 0.6, 0.6, 1.0, 1.0, True)),
        ]

        ranked = rank_memories(memories)

        assert ranked[0][0] == "high"
        assert ranked[1][0] == "mid"
        # "low" filtered out (below threshold)

    def test_filters_below_threshold_by_default(self):
        """Test items below threshold are filtered by default."""
        memories = [
            ("pass1", MemoryScore(0.8, 0.8, 0.8, 0.8, 0.8, 1.0, 1.0, True)),
            ("fail", MemoryScore(0.2, 0.2, 0.2, 0.2, 0.2, 1.0, 1.0, False)),
            ("pass2", MemoryScore(0.7, 0.7, 0.7, 0.7, 0.7, 1.0, 1.0, True)),
        ]

        ranked = rank_memories(memories)

        assert len(ranked) == 2
        assert all(m[0].startswith("pass") for m in ranked)

    def test_include_below_threshold_option(self):
        """Test include_below_threshold=True keeps all items."""
        memories = [
            ("pass", MemoryScore(0.8, 0.8, 0.8, 0.8, 0.8, 1.0, 1.0, True)),
            ("fail", MemoryScore(0.2, 0.2, 0.2, 0.2, 0.2, 1.0, 1.0, False)),
        ]

        ranked = rank_memories(memories, include_below_threshold=True)

        assert len(ranked) == 2
        assert ranked[0][0] == "pass"  # Still sorted by score
        assert ranked[1][0] == "fail"


class TestMemoryScoreOutput:
    """Tests for MemoryScore output."""

    def test_to_dict(self):
        """Test to_dict produces correct format."""
        score = MemoryScore(
            final_score=0.85,
            semantic_component=0.9,
            usage_component=0.7,
            confidence_component=0.8,
            recency_component=0.95,
            tier_multiplier=2.0,
            tag_boost=1.3,
            passes_threshold=True,
        )

        result = score.to_dict()

        assert result["final_score"] == 0.85
        assert result["semantic"] == 0.9
        assert result["usage"] == 0.7
        assert result["confidence"] == 0.8
        assert result["recency"] == 0.95
        assert result["tier_multiplier"] == 2.0
        assert result["tag_boost"] == 1.3
        assert result["passes"] is True
