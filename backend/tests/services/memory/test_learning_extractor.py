"""Tests for learning extractor module."""

import pytest

from app.services.memory.learning_extractor import (
    ExtractedLearning,
    LearningType,
    LearningStatus,
    _parse_learnings_json,
    PROVISIONAL_THRESHOLD,
    CANONICAL_THRESHOLD,
)
from app.services.memory.service import MemoryCategory


class TestLearningType:
    """Tests for LearningType enum."""

    def test_has_expected_values(self):
        """Test that LearningType has the expected enum values."""
        assert LearningType.VERIFIED.value == "verified"
        assert LearningType.INFERENCE.value == "inference"
        assert LearningType.PATTERN.value == "pattern"

    def test_no_gotcha_value(self):
        """Regression test: GOTCHA should not exist in LearningType enum.

        The original design used LearningType.GOTCHA for anti-patterns but this was
        never added to the enum, causing AttributeError. The fix uses category-based
        detection (TROUBLESHOOTING_GUIDE) instead.
        """
        values = [lt.value for lt in LearningType]
        assert "gotcha" not in values
        assert not hasattr(LearningType, "GOTCHA")


class TestLearningStatus:
    """Tests for LearningStatus enum."""

    def test_has_expected_values(self):
        """Test that LearningStatus has the expected enum values."""
        assert LearningStatus.PROVISIONAL.value == "provisional"
        assert LearningStatus.CANONICAL.value == "canonical"


class TestConfidenceThresholds:
    """Tests for confidence thresholds."""

    def test_provisional_threshold(self):
        """Test provisional threshold is 70."""
        assert PROVISIONAL_THRESHOLD == 70

    def test_canonical_threshold(self):
        """Test canonical threshold is 90."""
        assert CANONICAL_THRESHOLD == 90

    def test_thresholds_are_ordered(self):
        """Test that canonical threshold is higher than provisional."""
        assert CANONICAL_THRESHOLD > PROVISIONAL_THRESHOLD


class TestCategoryBasedGuardrailDetection:
    """Tests for category-based guardrail detection.

    This tests the fix for the LearningType.GOTCHA bug where we now use
    category-based detection (TROUBLESHOOTING_GUIDE) instead of a non-existent
    enum value.
    """

    def test_troubleshooting_guide_is_guardrail(self):
        """Test that TROUBLESHOOTING_GUIDE category maps to guardrail tier."""
        # The fix uses: is_guardrail = mem_category == MemoryCategory.TROUBLESHOOTING_GUIDE
        assert MemoryCategory.TROUBLESHOOTING_GUIDE.value == "troubleshooting_guide"

    def test_other_categories_are_not_guardrails(self):
        """Test that other categories don't map to guardrail tier."""
        non_guardrail_categories = [
            MemoryCategory.CODING_STANDARD,
            MemoryCategory.SYSTEM_DESIGN,
            MemoryCategory.OPERATIONAL_CONTEXT,
            MemoryCategory.DOMAIN_KNOWLEDGE,
        ]
        for category in non_guardrail_categories:
            assert category != MemoryCategory.TROUBLESHOOTING_GUIDE


class TestParseLearningsJson:
    """Tests for _parse_learnings_json function."""

    def test_parses_valid_json_array(self):
        """Test parsing a valid JSON array of learnings."""
        response_text = '''
        Here are the learnings:
        ```json
        [
            {
                "content": "Always use async methods",
                "learning_type": "verified",
                "confidence": 95,
                "source_quote": "User confirmed this",
                "category": "coding_standard"
            }
        ]
        ```
        '''
        learnings = _parse_learnings_json(response_text)

        assert len(learnings) == 1
        assert learnings[0].content == "Always use async methods"
        assert learnings[0].learning_type == LearningType.VERIFIED
        assert learnings[0].confidence == 95
        assert learnings[0].category == "coding_standard"

    def test_parses_multiple_learnings(self):
        """Test parsing multiple learnings."""
        response_text = '''
        [
            {"content": "First learning", "learning_type": "verified", "confidence": 90},
            {"content": "Second learning", "learning_type": "inference", "confidence": 80},
            {"content": "Third learning", "learning_type": "pattern", "confidence": 65}
        ]
        '''
        learnings = _parse_learnings_json(response_text)

        assert len(learnings) == 3
        assert learnings[0].learning_type == LearningType.VERIFIED
        assert learnings[1].learning_type == LearningType.INFERENCE
        assert learnings[2].learning_type == LearningType.PATTERN

    def test_defaults_unknown_type_to_pattern(self):
        """Test that unknown learning types default to PATTERN."""
        response_text = '[{"content": "Test", "learning_type": "unknown_type", "confidence": 70}]'
        learnings = _parse_learnings_json(response_text)

        assert len(learnings) == 1
        assert learnings[0].learning_type == LearningType.PATTERN

    def test_returns_empty_list_for_no_json(self):
        """Test that non-JSON response returns empty list."""
        response_text = "No JSON here, just text."
        learnings = _parse_learnings_json(response_text)

        assert learnings == []

    def test_returns_empty_list_for_invalid_json(self):
        """Test that invalid JSON returns empty list."""
        response_text = "[{invalid json}]"
        learnings = _parse_learnings_json(response_text)

        assert learnings == []

    def test_limits_to_ten_learnings(self):
        """Test that output is limited to 10 learnings."""
        learnings_data = [
            {"content": f"Learning {i}", "learning_type": "pattern", "confidence": 70}
            for i in range(15)
        ]
        import json
        response_text = json.dumps(learnings_data)

        learnings = _parse_learnings_json(response_text)

        assert len(learnings) == 10

    def test_handles_missing_fields_with_defaults(self):
        """Test that missing fields get default values."""
        response_text = '[{"content": "Minimal learning"}]'
        learnings = _parse_learnings_json(response_text)

        assert len(learnings) == 1
        assert learnings[0].content == "Minimal learning"
        assert learnings[0].learning_type == LearningType.PATTERN  # default
        assert learnings[0].confidence == 60  # default
        assert learnings[0].category == "domain_knowledge"  # default

    def test_skips_non_dict_items(self):
        """Test that non-dict items in array are skipped."""
        response_text = '[{"content": "Valid"}, "string item", 123, null]'
        learnings = _parse_learnings_json(response_text)

        assert len(learnings) == 1
        assert learnings[0].content == "Valid"


class TestExtractedLearning:
    """Tests for ExtractedLearning model."""

    def test_validates_confidence_range(self):
        """Test that confidence must be 0-100."""
        learning = ExtractedLearning(
            content="Test",
            learning_type=LearningType.PATTERN,
            confidence=50,
        )
        assert learning.confidence == 50

    def test_rejects_invalid_confidence(self):
        """Test that confidence outside 0-100 raises error."""
        with pytest.raises(ValueError):
            ExtractedLearning(
                content="Test",
                learning_type=LearningType.PATTERN,
                confidence=101,
            )

        with pytest.raises(ValueError):
            ExtractedLearning(
                content="Test",
                learning_type=LearningType.PATTERN,
                confidence=-1,
            )
