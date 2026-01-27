"""Tests for A/B variant system."""

import pytest

from app.services.memory.variants import (
    AGGRESSIVE_CONFIG,
    BASELINE_CONFIG,
    ENHANCED_CONFIG,
    MINIMAL_CONFIG,
    VARIANT_CONFIGS,
    MemoryVariant,
    RecencyConfig,
    ScoringWeights,
    TierMultipliers,
    assign_variant,
    get_variant_config,
)


class TestMemoryVariant:
    """Tests for MemoryVariant enum."""

    def test_all_variants_defined(self):
        """Test all expected variants exist."""
        assert MemoryVariant.BASELINE.value == "BASELINE"
        assert MemoryVariant.ENHANCED.value == "ENHANCED"
        assert MemoryVariant.MINIMAL.value == "MINIMAL"
        assert MemoryVariant.AGGRESSIVE.value == "AGGRESSIVE"

    def test_variant_is_string_enum(self):
        """Test variants are string-compatible."""
        assert str(MemoryVariant.BASELINE) == "MemoryVariant.BASELINE"
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

    def test_enhanced_config(self):
        """Test ENHANCED variant config has higher semantic weight."""
        config = ENHANCED_CONFIG
        assert config.variant == MemoryVariant.ENHANCED
        assert config.scoring_weights.semantic > BASELINE_CONFIG.scoring_weights.semantic
        assert config.min_relevance_threshold > BASELINE_CONFIG.min_relevance_threshold

    def test_minimal_config(self):
        """Test MINIMAL variant config has highest threshold."""
        config = MINIMAL_CONFIG
        assert config.variant == MemoryVariant.MINIMAL
        assert config.min_relevance_threshold == 0.50
        assert config.min_relevance_threshold > ENHANCED_CONFIG.min_relevance_threshold

    def test_aggressive_config(self):
        """Test AGGRESSIVE variant config has lowest threshold."""
        config = AGGRESSIVE_CONFIG
        assert config.variant == MemoryVariant.AGGRESSIVE
        assert config.min_relevance_threshold == 0.25
        assert config.min_relevance_threshold < BASELINE_CONFIG.min_relevance_threshold

    def test_all_configs_in_variant_configs_dict(self):
        """Test all variants have configs in VARIANT_CONFIGS."""
        for variant in MemoryVariant:
            assert variant in VARIANT_CONFIGS
            assert VARIANT_CONFIGS[variant].variant == variant


class TestGetVariantConfig:
    """Tests for get_variant_config function."""

    def test_get_by_enum(self):
        """Test getting config by enum."""
        config = get_variant_config(MemoryVariant.ENHANCED)
        assert config.variant == MemoryVariant.ENHANCED

    def test_get_by_string(self):
        """Test getting config by string name."""
        config = get_variant_config("MINIMAL")
        assert config.variant == MemoryVariant.MINIMAL

    def test_invalid_string_fallback(self):
        """Test invalid string falls back to BASELINE."""
        config = get_variant_config("INVALID")
        assert config.variant == MemoryVariant.BASELINE


class TestAssignVariant:
    """Tests for assign_variant function."""

    def test_determinism_same_inputs(self):
        """Test same inputs produce same variant (determinism)."""
        v1 = assign_variant(external_id="task-123", project_id="summitflow")
        v2 = assign_variant(external_id="task-123", project_id="summitflow")
        v3 = assign_variant(external_id="task-123", project_id="summitflow")

        assert v1 == v2 == v3

    def test_different_inputs_can_differ(self):
        """Test different inputs can produce different variants."""
        # Generate many variants to verify distribution works
        variants_seen = set()
        for i in range(1000):
            v = assign_variant(external_id=f"task-{i}", project_id="test")
            variants_seen.add(v)

        # Should see at least 3 different variants with 1000 samples
        assert len(variants_seen) >= 3

    def test_override_takes_precedence(self):
        """Test variant_override bypasses hash assignment."""
        v = assign_variant(
            external_id="task-123",
            project_id="summitflow",
            variant_override=MemoryVariant.AGGRESSIVE,
        )
        assert v == MemoryVariant.AGGRESSIVE

    def test_override_string(self):
        """Test variant_override works with string."""
        v = assign_variant(
            external_id="task-123",
            variant_override="ENHANCED",
        )
        assert v == MemoryVariant.ENHANCED

    def test_invalid_override_fallback(self):
        """Test invalid override falls back to BASELINE."""
        v = assign_variant(
            external_id="task-123",
            variant_override="INVALID",
        )
        assert v == MemoryVariant.BASELINE

    def test_no_identifiers_default_baseline(self):
        """Test no identifiers defaults to BASELINE."""
        v = assign_variant()
        assert v == MemoryVariant.BASELINE

    def test_only_external_id(self):
        """Test works with only external_id."""
        v = assign_variant(external_id="task-456")
        assert isinstance(v, MemoryVariant)

    def test_only_project_id(self):
        """Test works with only project_id."""
        v = assign_variant(project_id="agent-hub")
        assert isinstance(v, MemoryVariant)


class TestVariantDistribution:
    """Tests for variant bucket distribution."""

    def test_approximate_distribution(self):
        """Test variant distribution is approximately correct over many samples."""
        counts = {v: 0 for v in MemoryVariant}

        # Generate 10000 samples
        for i in range(10000):
            v = assign_variant(external_id=f"task-{i}", project_id=f"proj-{i % 100}")
            counts[v] += 1

        # Expected: 50% BASELINE, 30% ENHANCED, 10% MINIMAL, 10% AGGRESSIVE
        # Allow 10% margin of error due to hash distribution variance
        total = sum(counts.values())

        baseline_pct = counts[MemoryVariant.BASELINE] / total * 100
        enhanced_pct = counts[MemoryVariant.ENHANCED] / total * 100
        minimal_pct = counts[MemoryVariant.MINIMAL] / total * 100
        aggressive_pct = counts[MemoryVariant.AGGRESSIVE] / total * 100

        # Relaxed bounds - hash-based distribution has variance
        assert 40 <= baseline_pct <= 60, f"BASELINE: {baseline_pct}%"
        assert 20 <= enhanced_pct <= 40, f"ENHANCED: {enhanced_pct}%"
        assert 3 <= minimal_pct <= 20, f"MINIMAL: {minimal_pct}%"
        assert 3 <= aggressive_pct <= 20, f"AGGRESSIVE: {aggressive_pct}%"
