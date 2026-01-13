"""Tests for tier classifier."""

from app.services.tier_classifier import (
    Tier,
    classify_and_select_model,
    classify_request,
    get_model_for_tier,
)


class TestClassifyRequest:
    """Tests for classify_request function."""

    def test_simple_query_tier_1(self):
        """Simple queries should be tier 1."""
        assert classify_request("What time is it?") == Tier.TIER_1
        assert classify_request("Hello") == Tier.TIER_1

    def test_code_generation_tier_2(self):
        """Code generation should be tier 2."""
        assert classify_request("Write a function to sort a list") == Tier.TIER_2
        assert classify_request("Create a new class for users") == Tier.TIER_2
        assert classify_request("Generate a python script") == Tier.TIER_2

    def test_debugging_tier_3(self):
        """Debugging and optimization should be tier 3."""
        assert classify_request("Debug this code and explain the issue") == Tier.TIER_3
        assert classify_request("Optimize this function for performance") == Tier.TIER_3
        assert classify_request("Refactor this module") == Tier.TIER_3

    def test_architecture_tier_4(self):
        """Architecture and system design should be tier 4."""
        assert classify_request("Design the system architecture for this app") == Tier.TIER_4
        assert classify_request("What design pattern should I use?") == Tier.TIER_4
        assert classify_request("Analyze the root cause of this problem") == Tier.TIER_4
        assert classify_request("Plan a scalability strategy") == Tier.TIER_4

    def test_long_prompt_tier_3(self):
        """Long prompts should be at least tier 2-3."""
        long_prompt = "Here is some context. " * 100  # > 2000 chars
        assert classify_request(long_prompt) >= Tier.TIER_3

    def test_medium_prompt_tier_2(self):
        """Medium prompts should be at least tier 2."""
        medium_prompt = "Here is some context. " * 30  # > 500 chars
        assert classify_request(medium_prompt) >= Tier.TIER_2


class TestGetModelForTier:
    """Tests for get_model_for_tier function."""

    def test_tier_1_claude(self):
        """Tier 1 should return haiku for Claude."""
        model = get_model_for_tier(Tier.TIER_1, "claude")
        assert "haiku" in model.lower()

    def test_tier_1_gemini(self):
        """Tier 1 should return flash for Gemini."""
        model = get_model_for_tier(Tier.TIER_1, "gemini")
        assert "flash" in model.lower()

    def test_tier_4_claude(self):
        """Tier 4 should return opus for Claude."""
        model = get_model_for_tier(Tier.TIER_4, "claude")
        assert "opus" in model.lower()

    def test_tier_4_gemini(self):
        """Tier 4 should return pro for Gemini."""
        model = get_model_for_tier(Tier.TIER_4, "gemini")
        assert "pro" in model.lower()


class TestClassifyAndSelectModel:
    """Tests for classify_and_select_model function."""

    def test_explicit_model_override(self):
        """Explicit model should override tier selection."""
        tier, model = classify_and_select_model(
            prompt="Design the architecture",  # Would be tier 4
            explicit_model="claude-haiku-4-5-20250514",
        )
        assert tier == Tier.TIER_4  # Tier still classified correctly
        assert model == "claude-haiku-4-5-20250514"  # But explicit model used

    def test_auto_selection(self):
        """Without explicit model, auto-select based on tier."""
        tier, model = classify_and_select_model(
            prompt="Hello",
            provider="claude",
        )
        assert tier == Tier.TIER_1
        assert "haiku" in model.lower()

    def test_gemini_provider(self):
        """Should select Gemini models for gemini provider."""
        tier, model = classify_and_select_model(
            prompt="Write code",
            provider="gemini",
        )
        assert "gemini" in model.lower()
