"""Tests for adaptive index (ac-004, ac-005 verification)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.memory.adaptive_index import (
    AdaptiveIndex,
    IndexEntry,
    apply_demotion,
    build_adaptive_index,
    calculate_demotion_threshold,
    categorize_content,
    summarize_content,
)


class TestIndexEntry:
    """Tests for IndexEntry dataclass."""

    def test_default_values(self):
        """Test default values for index entry."""
        entry = IndexEntry(
            uuid="abc12345-full-uuid",
            short_id="abc12345",
            summary="Test summary",
            category="Testing",
        )

        assert entry.relevance_ratio == 0.5
        assert entry.loaded_count == 0
        assert entry.referenced_count == 0
        assert entry.is_demoted is False


class TestAdaptiveIndex:
    """Tests for AdaptiveIndex class."""

    def test_is_stale_no_refresh(self):
        """Test index is stale when never refreshed."""
        index = AdaptiveIndex()
        assert index.is_stale() is True

    def test_is_stale_within_ttl(self):
        """Test index is not stale within TTL."""
        now = datetime.now(UTC)
        index = AdaptiveIndex(last_refresh=now)
        assert index.is_stale(now + timedelta(seconds=60)) is False

    def test_is_stale_after_ttl(self):
        """Test index is stale after TTL."""
        now = datetime.now(UTC)
        index = AdaptiveIndex(last_refresh=now, ttl_seconds=60)
        assert index.is_stale(now + timedelta(seconds=120)) is True

    def test_get_active_entries_filters_demoted(self):
        """Test get_active_entries excludes demoted items."""
        entries = [
            IndexEntry("1", "1", "active", "Test", is_demoted=False),
            IndexEntry("2", "2", "demoted", "Test", is_demoted=True),
            IndexEntry("3", "3", "active2", "Test", is_demoted=False),
        ]
        index = AdaptiveIndex(entries=entries)

        active = index.get_active_entries()
        assert len(active) == 2
        assert all(not e.is_demoted for e in active)

    def test_format_for_injection_empty(self):
        """Test format returns empty string for empty index."""
        index = AdaptiveIndex()
        assert index.format_for_injection() == ""

    def test_format_for_injection_groups_by_category(self):
        """Test format groups entries by category."""
        entries = [
            IndexEntry("1", "11111111", "test pattern", "Testing"),
            IndexEntry("2", "22222222", "commit rule", "Git"),
            IndexEntry("3", "33333333", "another test", "Testing"),
        ]
        index = AdaptiveIndex(entries=entries)

        result = index.format_for_injection()

        assert "## Adaptive Index" in result
        assert "**Testing**:" in result
        assert "**Git**:" in result
        assert "[M:11111111]" in result
        assert "[M:22222222]" in result


class TestCategorizeContent:
    """Tests for categorize_content function."""

    def test_testing_keywords(self):
        """Test testing keywords are categorized correctly."""
        assert categorize_content("Always use pytest fixtures") == "Testing"
        assert categorize_content("Mock external services") == "Testing"
        assert categorize_content("AAA pattern for tests") == "Testing"

    def test_git_keywords(self):
        """Test git keywords are categorized correctly."""
        assert categorize_content("Never direct git commit") == "Git"
        assert categorize_content("Push to remote after review") == "Git"

    def test_error_keywords(self):
        """Test error keywords are categorized correctly."""
        assert categorize_content("Handle exceptions properly") == "Errors"
        assert categorize_content("Bug tracking is important") == "Errors"

    def test_default_category(self):
        """Test content without keywords gets General category."""
        assert categorize_content("Some random content here") == "General"


class TestSummarizeContent:
    """Tests for summarize_content function."""

    def test_short_content_unchanged(self):
        """Test short content is returned unchanged."""
        content = "Short content"
        assert summarize_content(content) == "Short content"

    def test_first_sentence_extracted(self):
        """Test first sentence is extracted."""
        content = "First sentence. Second sentence. Third."
        assert summarize_content(content) == "First sentence"

    def test_long_content_truncated(self):
        """Test long content is truncated with ellipsis."""
        content = "A" * 100
        result = summarize_content(content, max_length=50)
        assert len(result) <= 50
        assert result.endswith("...")

    def test_newlines_removed(self):
        """Test newlines are replaced with spaces."""
        content = "Line one\nLine two\nLine three"
        result = summarize_content(content)
        assert "\n" not in result


class TestCalculateDemotionThreshold:
    """Tests for calculate_demotion_threshold function."""

    def test_insufficient_data_returns_none(self):
        """Test returns None with insufficient data."""
        entries = [
            IndexEntry("1", "1", "s", "C", loaded_count=5),  # Below min samples
            IndexEntry("2", "2", "s", "C", loaded_count=3),
        ]
        assert calculate_demotion_threshold(entries) is None

    def test_calculates_threshold_from_distribution(self):
        """Test threshold is median - stdev (ac-005)."""
        entries = [
            IndexEntry("1", "1", "s", "C", relevance_ratio=0.8, loaded_count=20),
            IndexEntry("2", "2", "s", "C", relevance_ratio=0.6, loaded_count=20),
            IndexEntry("3", "3", "s", "C", relevance_ratio=0.4, loaded_count=20),
            IndexEntry("4", "4", "s", "C", relevance_ratio=0.2, loaded_count=20),
        ]

        threshold = calculate_demotion_threshold(entries)

        # Median of [0.8, 0.6, 0.4, 0.2] = 0.5
        # Stdev ≈ 0.258
        # Threshold ≈ 0.5 - 0.258 ≈ 0.242
        assert threshold is not None
        assert 0.2 <= threshold <= 0.3

    def test_threshold_not_negative(self):
        """Test threshold is never negative."""
        # All very low ratios
        entries = [
            IndexEntry("1", "1", "s", "C", relevance_ratio=0.05, loaded_count=20),
            IndexEntry("2", "2", "s", "C", relevance_ratio=0.03, loaded_count=20),
            IndexEntry("3", "3", "s", "C", relevance_ratio=0.02, loaded_count=20),
        ]

        threshold = calculate_demotion_threshold(entries)
        assert threshold is not None
        assert threshold >= 0


class TestApplyDemotion:
    """Tests for apply_demotion function."""

    def test_no_demotion_without_threshold(self):
        """Test nothing demoted when threshold is None."""
        entries = [
            IndexEntry("1", "1", "s", "C", relevance_ratio=0.1, loaded_count=50),
        ]

        result = apply_demotion(entries, threshold=None)
        assert result[0].is_demoted is False

    def test_below_threshold_demoted(self):
        """Test entries below threshold are demoted (ac-005)."""
        entries = [
            IndexEntry("1", "1", "s", "C", relevance_ratio=0.1, loaded_count=20),
            IndexEntry("2", "2", "s", "C", relevance_ratio=0.5, loaded_count=20),
        ]

        result = apply_demotion(entries, threshold=0.3)

        assert result[0].is_demoted is True  # 0.1 < 0.3
        assert result[1].is_demoted is False  # 0.5 >= 0.3

    def test_requires_sufficient_samples(self):
        """Test demotion requires statistically significant samples."""
        entries = [
            IndexEntry("1", "1", "s", "C", relevance_ratio=0.1, loaded_count=5),  # Too few
            IndexEntry("2", "2", "s", "C", relevance_ratio=0.1, loaded_count=20),  # Enough
        ]

        result = apply_demotion(entries, threshold=0.3)

        assert result[0].is_demoted is False  # Not enough samples
        assert result[1].is_demoted is True  # Enough samples, below threshold


class TestBuildAdaptiveIndex:
    """Tests for build_adaptive_index function (ac-004)."""

    @pytest.mark.asyncio
    async def test_index_includes_all_mandates(self):
        """Test index includes all mandates on cold start (ac-004)."""
        golden_standards = [
            {"uuid": "uuid-1", "content": "Always use async patterns"},
            {"uuid": "uuid-2", "content": "Never commit directly"},
            {"uuid": "uuid-3", "content": "Test with AAA pattern"},
        ]

        index = await build_adaptive_index(golden_standards)

        # All mandates should be in the index
        assert len(index.entries) == 3
        uuids = {e.uuid for e in index.entries}
        assert "uuid-1" in uuids
        assert "uuid-2" in uuids
        assert "uuid-3" in uuids

    @pytest.mark.asyncio
    async def test_descriptive_format(self):
        """Test index entries have descriptive one-liner summaries (ac-004)."""
        golden_standards = [
            {
                "uuid": "uuid-1",
                "content": "Always use pytest fixtures for testing. This ensures consistency.",
            },
        ]

        index = await build_adaptive_index(golden_standards)

        # Summary should be meaningful one-liner
        assert len(index.entries) == 1
        entry = index.entries[0]
        assert len(entry.summary) <= 60
        assert "pytest fixtures" in entry.summary.lower()

    @pytest.mark.asyncio
    async def test_usage_stats_applied(self):
        """Test usage stats are applied to entries."""
        golden_standards = [
            {"uuid": "uuid-1", "content": "Test content"},
        ]
        usage_stats = {
            "uuid-1": {"loaded_count": 100, "referenced_count": 80},
        }

        index = await build_adaptive_index(golden_standards, usage_stats)

        entry = index.entries[0]
        assert entry.loaded_count == 100
        assert entry.referenced_count == 80
        assert entry.relevance_ratio == 0.8

    @pytest.mark.asyncio
    async def test_empty_input(self):
        """Test empty input produces empty index."""
        index = await build_adaptive_index([])
        assert len(index.entries) == 0

    @pytest.mark.asyncio
    async def test_skips_invalid_entries(self):
        """Test skips entries without uuid or content."""
        golden_standards = [
            {"uuid": "valid", "content": "Valid content"},
            {"uuid": "", "content": "Missing uuid"},
            {"uuid": "no-content", "content": ""},
        ]

        index = await build_adaptive_index(golden_standards)

        assert len(index.entries) == 1
        assert index.entries[0].uuid == "valid"


class TestDemotionLogic:
    """Tests for demotion logic (ac-005)."""

    @pytest.mark.asyncio
    async def test_demotion_logic(self):
        """Test mandate demoted after sufficient low-relevance samples (ac-005)."""
        golden_standards = [
            {"uuid": "high-usage", "content": "High usage rule"},
            {"uuid": "low-usage", "content": "Low usage rule"},
            {"uuid": "medium-usage", "content": "Medium usage rule"},
        ]
        usage_stats = {
            "high-usage": {"loaded_count": 100, "referenced_count": 80},  # 0.8 ratio
            "low-usage": {"loaded_count": 100, "referenced_count": 5},  # 0.05 ratio
            "medium-usage": {"loaded_count": 100, "referenced_count": 50},  # 0.5 ratio
        }

        index = await build_adaptive_index(golden_standards, usage_stats)

        # Find entries
        high = next(e for e in index.entries if e.uuid == "high-usage")
        low = next(e for e in index.entries if e.uuid == "low-usage")
        next(e for e in index.entries if e.uuid == "medium-usage")

        # Low-usage should be demoted (below threshold)
        # High and medium should not be demoted
        assert low.is_demoted is True, "Low-usage entry should be demoted"
        assert high.is_demoted is False, "High-usage entry should not be demoted"
        # Medium depends on threshold calculation

    @pytest.mark.asyncio
    async def test_no_demotion_without_samples(self):
        """Test no demotion when entries lack sufficient samples."""
        golden_standards = [
            {"uuid": "uuid-1", "content": "Rule 1"},
            {"uuid": "uuid-2", "content": "Rule 2"},
        ]
        # Low sample counts
        usage_stats = {
            "uuid-1": {"loaded_count": 3, "referenced_count": 0},
            "uuid-2": {"loaded_count": 5, "referenced_count": 0},
        }

        index = await build_adaptive_index(golden_standards, usage_stats)

        # Neither should be demoted (insufficient samples)
        assert all(not e.is_demoted for e in index.entries)
