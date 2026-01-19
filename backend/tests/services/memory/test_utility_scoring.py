"""Tests for utility score computation and retrieval sorting.

Utility score = success_count / referenced_count
Used for prioritizing which rules to inject in context.
"""

import pytest


class TestUtilityScoreComputation:
    """Tests for utility score calculation."""

    def test_utility_score_formula(self):
        """Test utility score = success / referenced."""
        # Example: 8 successes out of 10 references = 0.8 utility
        success_count = 8
        referenced_count = 10

        utility_score = success_count / referenced_count

        assert utility_score == 0.8

    def test_utility_score_perfect(self):
        """Test perfect utility score (always successful)."""
        success_count = 5
        referenced_count = 5

        utility_score = success_count / referenced_count

        assert utility_score == 1.0

    def test_utility_score_zero_success(self):
        """Test zero utility score (never successful)."""
        success_count = 0
        referenced_count = 10

        utility_score = success_count / referenced_count

        assert utility_score == 0.0

    def test_utility_score_zero_references(self):
        """Test utility score when no references (avoid division by zero)."""
        success_count = 0
        referenced_count = 0

        # System should handle this gracefully
        if referenced_count > 0:
            utility_score = success_count / referenced_count
        else:
            utility_score = 0.0

        assert utility_score == 0.0


class TestUtilityScoreInNeo4j:
    """Tests for Neo4j utility score computation."""

    def test_neo4j_cypher_formula(self):
        """Test the Cypher formula matches expected behavior."""
        # This mirrors the Cypher in usage_tracker._flush_to_neo4j:
        # e.utility_score = CASE
        #     WHEN (COALESCE(e.referenced_count, 0)) > 0
        #     THEN toFloat(COALESCE(e.success_count, 0)) / toFloat(e.referenced_count)
        #     ELSE 0.0
        # END

        # Test case 1: Normal case
        referenced_count = 10
        success_count = 8
        expected = 0.8
        actual = float(success_count) / float(referenced_count) if referenced_count > 0 else 0.0
        assert actual == expected

        # Test case 2: No references
        referenced_count = 0
        success_count = 0
        expected = 0.0
        actual = float(success_count) / float(referenced_count) if referenced_count > 0 else 0.0
        assert actual == expected

        # Test case 3: Null coalesce simulation
        referenced_count = None
        success_count = None
        expected = 0.0
        ref = referenced_count if referenced_count is not None else 0
        suc = success_count if success_count is not None else 0
        actual = float(suc) / float(ref) if ref > 0 else 0.0
        assert actual == expected


class TestRetrievalSorting:
    """Tests for retrieval sorting by utility score."""

    def test_sort_by_utility_score_descending(self):
        """Test rules are sorted by utility_score descending."""
        rules = [
            {"uuid": "rule-1", "utility_score": 0.5},
            {"uuid": "rule-2", "utility_score": 0.9},
            {"uuid": "rule-3", "utility_score": 0.3},
            {"uuid": "rule-4", "utility_score": 0.7},
        ]

        sorted_rules = sorted(rules, key=lambda r: r["utility_score"], reverse=True)

        assert sorted_rules[0]["uuid"] == "rule-2"  # 0.9
        assert sorted_rules[1]["uuid"] == "rule-4"  # 0.7
        assert sorted_rules[2]["uuid"] == "rule-1"  # 0.5
        assert sorted_rules[3]["uuid"] == "rule-3"  # 0.3

    def test_sort_stable_for_equal_scores(self):
        """Test sorting is stable for equal utility scores."""
        rules = [
            {"uuid": "rule-1", "utility_score": 0.5, "created_at": "2025-01-01"},
            {"uuid": "rule-2", "utility_score": 0.5, "created_at": "2025-01-02"},
            {"uuid": "rule-3", "utility_score": 0.5, "created_at": "2025-01-03"},
        ]

        # Python's sort is stable, so equal items maintain order
        sorted_rules = sorted(rules, key=lambda r: r["utility_score"], reverse=True)

        # All have same score, order preserved
        assert sorted_rules[0]["uuid"] == "rule-1"
        assert sorted_rules[1]["uuid"] == "rule-2"
        assert sorted_rules[2]["uuid"] == "rule-3"

    def test_fallback_to_created_at_for_zero_score(self):
        """Test rules with zero utility fall back to created_at ordering."""
        rules = [
            {"uuid": "rule-1", "utility_score": 0.0, "created_at": "2025-01-03"},
            {"uuid": "rule-2", "utility_score": 0.0, "created_at": "2025-01-01"},
            {"uuid": "rule-3", "utility_score": 0.0, "created_at": "2025-01-02"},
        ]

        # Sort by utility then by created_at (most recent first for new rules)
        sorted_rules = sorted(
            rules,
            key=lambda r: (r["utility_score"], r["created_at"]),
            reverse=True,
        )

        # All utility=0, so sorted by created_at descending
        assert sorted_rules[0]["uuid"] == "rule-1"  # 2025-01-03
        assert sorted_rules[1]["uuid"] == "rule-3"  # 2025-01-02
        assert sorted_rules[2]["uuid"] == "rule-2"  # 2025-01-01


class TestHighUtilityRulesPrioritized:
    """Tests that high utility rules are prioritized in context injection."""

    def test_high_utility_first_in_limited_context(self):
        """Test high utility rules appear first when context is limited."""
        rules = [
            {"uuid": "low-utility", "content": "Low", "utility_score": 0.2},
            {"uuid": "high-utility", "content": "High", "utility_score": 0.9},
            {"uuid": "medium-utility", "content": "Medium", "utility_score": 0.5},
        ]

        # Sort by utility (desc) and take top 2
        sorted_rules = sorted(rules, key=lambda r: r["utility_score"], reverse=True)
        top_rules = sorted_rules[:2]

        assert top_rules[0]["uuid"] == "high-utility"
        assert top_rules[1]["uuid"] == "medium-utility"
        # low-utility is excluded due to limit
