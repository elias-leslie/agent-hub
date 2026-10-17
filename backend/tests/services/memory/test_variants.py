"""Tests for the memory injection scoring config (BASELINE only)."""

import pytest

from app.services.memory.variants import (
    BASELINE_CONFIG,
    MemoryVariant,
    RecencyConfig,
    ScoringWeights,
    TierMultipliers,
    get_variant_config,
)


class TestMemoryVariant:
    """Tests for MemoryVariant enum."""

    def test_only_baseline_is_defined(self):
        """The retired A/B variants are gone; BASELINE is the only config."""
        assert [variant.value for variant in MemoryVariant] == ["BASELINE"]

    def test_variant_is_string_enum(self):
        """Test variants are string-compatible."""
        assert str(MemoryVariant.BASELINE) == "BASELINE"
        assert MemoryVariant.BASELINE == "BASELINE"


class TestScoringWeights:
    """Tests for ScoringWeights dataclass."""

    def test_default_weights_sum_to_one(self):
        """Test default weights sum to 1.0."""
        weights = ScoringWeights()
        total = weights.semantic + weights.usage + weights.confidence + weights.recency
        assert abs(total - 1.0) < 0.001

    def test_custom_weights_sum_to_one(self):
        """Test valid custom weights."""
        weights = ScoringWeights(
            semantic=0.5,
            usage=0.3,
            confidence=0.1,
            recency=0.1,
        )
        total = weights.semantic + weights.usage + weights.confidence + weights.recency
        assert abs(total - 1.0) < 0.001

    def test_invalid_weights_raise_error(self):
        """Test weights not summing to 1.0 raise ValueError."""
        with pytest.raises(ValueError, match=r"must sum to 1\.0"):
            ScoringWeights(
                semantic=0.5,
                usage=0.5,
                confidence=0.5,
                recency=0.5,
            )


class TestTierMultipliers:
    """Tests for TierMultipliers dataclass."""

    def test_default_values(self):
        """Test default tier multipliers."""
        tiers = TierMultipliers()
        assert tiers.mandate == 2.0
        assert tiers.guardrail == 1.5
        assert tiers.reference == 1.0

    def test_custom_values(self):
        """Test custom tier multipliers."""
        tiers = TierMultipliers(
            mandate=3.0,
            guardrail=2.0,
            reference=1.5,
        )
        assert tiers.mandate == 3.0
        assert tiers.guardrail == 2.0


class TestRecencyConfig:
    """Tests for RecencyConfig dataclass."""

    def test_default_values(self):
        """Test default recency half-lives."""
        config = RecencyConfig()
        assert config.mandate_half_life_days == 30
        assert config.reference_half_life_days == 7


class TestVariantConfig:
    """Tests for VariantConfig dataclass."""

    def test_baseline_config(self):
        """Test BASELINE variant config."""
        config = BASELINE_CONFIG
        assert config.variant == MemoryVariant.BASELINE
        assert config.min_relevance_threshold == 0.35
        assert config.golden_standard_min_similarity == 0.25
        assert config.max_reference_items == 6
        assert config.max_query_selected_references == 3

    def test_get_variant_config_is_baseline(self):
        assert get_variant_config() is BASELINE_CONFIG
