"""Tests for score-based model selector."""

import pytest

from app.constants import MODEL_CATALOG, MODEL_CATALOG_BY_ID, SCORE_WEIGHTS
from app.constants.models import CLAUDE_OPUS, CLAUDE_SONNET
from app.services.model_selector import (
    ComplexityTier,
    QualityPreference,
    classify_complexity,
    detect_category_weights,
    detect_required_capabilities,
    filter_by_capabilities,
    find_equivalent,
    select_model,
    select_model_for_request,
    weighted_score,
)


@pytest.mark.unit
class TestClassifyComplexity:
    """Tests for classify_complexity function."""

    def test_simple_query_tier_1(self) -> None:
        """Simple queries should be tier 1."""
        assert classify_complexity("What time is it?") == ComplexityTier.TIER_1
        assert classify_complexity("Hello") == ComplexityTier.TIER_1

    def test_code_generation_tier_2(self) -> None:
        """Code generation should be tier 2."""
        assert classify_complexity("Write a function to sort a list") == ComplexityTier.TIER_2
        assert classify_complexity("Create a new class for users") == ComplexityTier.TIER_2

    def test_debugging_tier_3(self) -> None:
        """Debugging should be tier 3."""
        assert classify_complexity("Debug this code") == ComplexityTier.TIER_3
        assert classify_complexity("Refactor this module") == ComplexityTier.TIER_3

    def test_architecture_tier_4(self) -> None:
        """Architecture should be tier 4."""
        assert classify_complexity("Design the system architecture") == ComplexityTier.TIER_4
        assert classify_complexity("Analyze the root cause") == ComplexityTier.TIER_4


@pytest.mark.unit
class TestDetectCategoryWeights:
    """Tests for detect_category_weights function."""

    def test_default_weights(self) -> None:
        """Should return default weights when no context."""
        weights = detect_category_weights()
        assert sum(weights.values()) == pytest.approx(1.0)
        # Should be normalized SCORE_WEIGHTS
        for category in SCORE_WEIGHTS:
            assert category in weights

    def test_coder_agent_boosts_coding(self) -> None:
        """Coder agent should boost coding weight."""
        weights = detect_category_weights(agent_slug="coder")
        assert weights["coding"] == max(weights.values())

    def test_designer_agent_boosts_design(self) -> None:
        """Designer agent should boost design weight."""
        weights = detect_category_weights(agent_slug="designer")
        assert weights["design"] == max(weights.values())

    def test_image_generation_prompt(self) -> None:
        """Image generation prompts should boost design."""
        weights = detect_category_weights(prompt="Generate an image of a sunset")
        assert weights["design"] == max(weights.values())


@pytest.mark.unit
class TestDetectRequiredCapabilities:
    """Tests for detect_required_capabilities function."""

    def test_no_capabilities_required(self) -> None:
        """Simple prompts should require no special capabilities."""
        caps = detect_required_capabilities(prompt="Write a function")
        assert caps == {}

    def test_image_generation_required(self) -> None:
        """Image generation prompts should require can_generate_images."""
        caps = detect_required_capabilities(prompt="Create an image of a cat")
        assert caps.get("can_generate_images") is True

    def test_vision_required(self) -> None:
        """Vision prompts should require has_vision."""
        caps = detect_required_capabilities(prompt="Look at this image and describe it")
        assert caps.get("has_vision") is True

    def test_image_editing_required(self) -> None:
        """Image editing prompts should require can_edit_images."""
        caps = detect_required_capabilities(prompt="Edit this image")
        assert caps.get("can_edit_images") is True


@pytest.mark.unit
class TestFilterByCapabilities:
    """Tests for filter_by_capabilities function."""

    def test_no_filter_returns_all(self) -> None:
        """Empty capabilities should return all models."""
        filtered = filter_by_capabilities(MODEL_CATALOG, {})
        assert len(filtered) == len(MODEL_CATALOG)

    def test_vision_filter(self) -> None:
        """Vision requirement should filter to vision models."""
        filtered = filter_by_capabilities(MODEL_CATALOG, {"has_vision": True})
        assert all(m.capabilities.has_vision for m in filtered)

    def test_image_generation_filter(self) -> None:
        """Image generation requirement should filter correctly."""
        filtered = filter_by_capabilities(MODEL_CATALOG, {"can_generate_images": True})
        assert all(m.capabilities.can_generate_images for m in filtered)
        assert len(filtered) < len(MODEL_CATALOG)  # Should filter some out


@pytest.mark.unit
class TestWeightedScore:
    """Tests for weighted_score function."""

    def test_default_weights(self) -> None:
        """Should calculate weighted score with default weights."""
        model = MODEL_CATALOG[0]
        score = weighted_score(model, SCORE_WEIGHTS)
        # Should match composite score
        assert score == pytest.approx(model.scores.composite, abs=0.1)

    def test_custom_weights(self) -> None:
        """Should use custom weights."""
        model = MODEL_CATALOG[0]
        custom_weights = {
            "coding": 1.0,
            "reasoning": 0.0,
            "planning": 0.0,
            "tool_use": 0.0,
            "instruction": 0.0,
            "design": 0.0,
        }
        score = weighted_score(model, custom_weights)
        assert score == model.scores.coding


@pytest.mark.unit
class TestSelectModel:
    """Tests for select_model function."""

    def test_tier_1_returns_cheap_model(self) -> None:
        """Tier 1 should return a cheaper model."""
        model = select_model(ComplexityTier.TIER_1, preference=QualityPreference.ECONOMY)
        assert model.scores.composite >= 40

    def test_tier_4_returns_advanced_model(self) -> None:
        """Tier 4 with advanced preference should return high-quality model."""
        model = select_model(ComplexityTier.TIER_4, preference=QualityPreference.ADVANCED)
        assert model.scores.composite >= 80

    def test_provider_filter(self) -> None:
        """Should filter by provider."""
        model = select_model(ComplexityTier.TIER_2, provider="claude")
        assert model.provider == "claude"

    def test_economy_prefers_cheap(self) -> None:
        """Economy preference should minimize cost."""
        model = select_model(ComplexityTier.TIER_2, preference=QualityPreference.ECONOMY)
        # Should be one of the cheaper models
        assert model.cost.input_per_m + model.cost.output_per_m < 5.0

    def test_advanced_prefers_quality(self) -> None:
        """Advanced preference should maximize quality."""
        model = select_model(ComplexityTier.TIER_3, preference=QualityPreference.ADVANCED)
        # Should be a high-scoring model
        assert model.scores.composite >= 75


@pytest.mark.unit
class TestFindEquivalent:
    """Tests for find_equivalent function."""

    def test_find_equivalent_in_different_provider(self) -> None:
        """Should find equivalent model in different provider."""
        claude_sonnet = CLAUDE_SONNET
        gemini_equivalent = find_equivalent(claude_sonnet, "gemini")
        assert gemini_equivalent is not None
        assert "gemini" in gemini_equivalent.lower()

    def test_unknown_model_returns_none(self) -> None:
        """Unknown model should return None."""
        result = find_equivalent("unknown-model-xyz", "claude")
        assert result is None

    def test_equivalent_has_similar_score(self) -> None:
        """Equivalent should have similar composite score."""
        source_id = CLAUDE_OPUS
        source_model = MODEL_CATALOG_BY_ID[source_id]
        equivalent_id = find_equivalent(source_id, "gemini")
        if equivalent_id:
            equiv_model = MODEL_CATALOG_BY_ID[equivalent_id]
            # Should be within 10 points
            assert abs(source_model.scores.composite - equiv_model.scores.composite) <= 10


@pytest.mark.unit
class TestSelectModelForRequest:
    """Tests for select_model_for_request function."""

    def test_simple_request(self) -> None:
        """Simple request should work."""
        model = select_model_for_request("Hello world")
        assert model is not None
        assert model.id in MODEL_CATALOG_BY_ID

    def test_coding_request(self) -> None:
        """Coding request should prefer coding-capable models."""
        model = select_model_for_request(
            "Write a Python function to parse JSON",
            preference=QualityPreference.ADVANCED,
        )
        # Should be a high-scoring coding model
        assert model.scores.coding >= 70

    def test_image_generation_request(self) -> None:
        """Image generation should require image capabilities."""
        model = select_model_for_request("Generate an image of a mountain")
        assert model.capabilities.can_generate_images

    def test_provider_constraint(self) -> None:
        """Should respect provider constraint."""
        model = select_model_for_request("Write code", provider="claude")
        assert model.provider == "claude"
