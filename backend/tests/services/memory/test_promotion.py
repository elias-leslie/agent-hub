"""Tests for promotion module."""

import pytest

from app.services.memory.promotion import (
    SIMILARITY_THRESHOLD,
    PromoteRequest,
    PromotionResult,
    ReinforcementResult,
    _extract_confidence,
)


class TestPromotionResult:
    """Tests for PromotionResult model."""

    def test_default_values(self):
        """Test PromotionResult default values."""
        result = PromotionResult(success=True, message="test")
        assert result.success
        assert not result.promoted
        assert result.episode_uuid is None
        assert result.message == "test"
        assert result.previous_status is None
        assert result.new_status is None

    def test_full_result(self):
        """Test PromotionResult with all fields."""
        result = PromotionResult(
            success=True,
            promoted=True,
            episode_uuid="uuid-123",
            message="Promoted successfully",
            previous_status="provisional",
            new_status="canonical",
        )
        assert result.success
        assert result.promoted
        assert result.episode_uuid == "uuid-123"
        assert result.previous_status == "provisional"
        assert result.new_status == "canonical"


class TestPromoteRequest:
    """Tests for PromoteRequest model."""

    def test_required_uuid(self):
        """Test episode_uuid is required."""
        request = PromoteRequest(episode_uuid="uuid-456")
        assert request.episode_uuid == "uuid-456"
        assert request.reason is None

    def test_with_reason(self):
        """Test request with reason."""
        request = PromoteRequest(
            episode_uuid="uuid-789",
            reason="User verified this rule",
        )
        assert request.reason == "User verified this rule"


class TestReinforcementResult:
    """Tests for ReinforcementResult model."""

    def test_default_values(self):
        """Test ReinforcementResult default values."""
        result = ReinforcementResult()
        assert not result.found_match
        assert not result.promoted
        assert result.matched_uuid is None
        assert result.new_confidence is None

    def test_match_found_result(self):
        """Test result when match is found."""
        result = ReinforcementResult(
            found_match=True,
            promoted=True,
            matched_uuid="matched-uuid",
            new_confidence=95.0,
        )
        assert result.found_match
        assert result.promoted
        assert result.matched_uuid == "matched-uuid"
        assert result.new_confidence == 95.0


class TestSimilarityThreshold:
    """Tests for similarity threshold constant."""

    def test_threshold_value(self):
        """Test SIMILARITY_THRESHOLD is 0.8."""
        assert SIMILARITY_THRESHOLD == 0.8

    def test_threshold_in_valid_range(self):
        """Test threshold is in valid range (0-1)."""
        assert 0 < SIMILARITY_THRESHOLD < 1


class TestExtractConfidence:
    """Tests for _extract_confidence function."""

    def test_extracts_integer_confidence(self):
        """Test extracting integer confidence value."""
        source_desc = "coding_standard reference source:rule_migration confidence:85"
        assert _extract_confidence(source_desc) == 85.0

    def test_extracts_decimal_confidence(self):
        """Test extracting decimal confidence value."""
        source_desc = "source:learning confidence:87.5 status:provisional"
        assert _extract_confidence(source_desc) == 87.5

    def test_extracts_confidence_at_start(self):
        """Test extracting confidence at start of string."""
        source_desc = "confidence:100 source:golden_standard"
        assert _extract_confidence(source_desc) == 100.0

    def test_extracts_confidence_at_end(self):
        """Test extracting confidence at end of string."""
        source_desc = "source:rule_migration confidence:70"
        assert _extract_confidence(source_desc) == 70.0

    def test_returns_default_for_missing_confidence(self):
        """Test returns default 70.0 when confidence is missing."""
        source_desc = "coding_standard reference source:rule_migration"
        assert _extract_confidence(source_desc) == 70.0

    def test_returns_default_for_empty_string(self):
        """Test returns default 70.0 for empty string."""
        assert _extract_confidence("") == 70.0

    def test_returns_default_for_malformed(self):
        """Test returns default 70.0 for malformed confidence."""
        source_desc = "confidence: 85"  # Space after colon
        assert _extract_confidence(source_desc) == 70.0

    def test_first_match_wins(self):
        """Test first confidence value is used if multiple exist."""
        source_desc = "confidence:90 other:123 confidence:80"
        assert _extract_confidence(source_desc) == 90.0
