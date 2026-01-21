"""Tests for collect_baseline_metrics.py script."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# Add scripts to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from collect_baseline_metrics import (
    BaselineReport,
    VariantMetrics,
    calculate_citation_rate,
    generate_markdown_report,
)


class TestVariantMetrics:
    """Tests for VariantMetrics dataclass."""

    def test_success_rate_calculation(self):
        """Test success rate is calculated correctly."""
        metrics = VariantMetrics(
            variant="BASELINE",
            total_injections=100,
            successful_tasks=80,
            failed_tasks=20,
            unknown_outcome=0,
            total_retries=10,
            avg_latency_ms=50.0,
            avg_tokens=200,
            avg_mandates=3.0,
            avg_guardrails=2.0,
            avg_references=5.0,
            citation_rate=0.6,
            total_memories_loaded=100,
            total_memories_cited=60,
        )

        assert metrics.success_rate == 0.8

    def test_success_rate_with_zero_known(self):
        """Test success rate returns 0 when no known outcomes."""
        metrics = VariantMetrics(
            variant="BASELINE",
            total_injections=100,
            successful_tasks=0,
            failed_tasks=0,
            unknown_outcome=100,
            total_retries=0,
            avg_latency_ms=50.0,
            avg_tokens=200,
            avg_mandates=3.0,
            avg_guardrails=2.0,
            avg_references=5.0,
            citation_rate=0.0,
            total_memories_loaded=0,
            total_memories_cited=0,
        )

        assert metrics.success_rate == 0.0

    def test_retry_rate_calculation(self):
        """Test retry rate is calculated correctly."""
        metrics = VariantMetrics(
            variant="BASELINE",
            total_injections=100,
            successful_tasks=80,
            failed_tasks=20,
            unknown_outcome=0,
            total_retries=150,
            avg_latency_ms=50.0,
            avg_tokens=200,
            avg_mandates=3.0,
            avg_guardrails=2.0,
            avg_references=5.0,
            citation_rate=0.6,
            total_memories_loaded=100,
            total_memories_cited=60,
        )

        assert metrics.retry_rate == 1.5

    def test_retry_rate_with_zero_injections(self):
        """Test retry rate returns 0 when no injections."""
        metrics = VariantMetrics(
            variant="BASELINE",
            total_injections=0,
            successful_tasks=0,
            failed_tasks=0,
            unknown_outcome=0,
            total_retries=0,
            avg_latency_ms=0.0,
            avg_tokens=0,
            avg_mandates=0.0,
            avg_guardrails=0.0,
            avg_references=0.0,
            citation_rate=0.0,
            total_memories_loaded=0,
            total_memories_cited=0,
        )

        assert metrics.retry_rate == 0.0


class TestCalculateCitationRate:
    """Tests for calculate_citation_rate function."""

    def test_normal_calculation(self):
        """Test normal citation rate calculation."""
        assert calculate_citation_rate(100, 60) == 0.6

    def test_zero_loaded(self):
        """Test citation rate with zero loaded returns 0."""
        assert calculate_citation_rate(0, 0) == 0.0

    def test_all_cited(self):
        """Test citation rate when all memories cited."""
        assert calculate_citation_rate(50, 50) == 1.0


class TestGenerateMarkdownReport:
    """Tests for generate_markdown_report function."""

    def test_empty_report(self):
        """Test report generation with no metrics data."""
        report = BaselineReport(
            start_date=datetime.now(UTC) - timedelta(days=7),
            end_date=datetime.now(UTC),
            total_injections=0,
            variant_metrics={},
            daily_counts={},
            query_distribution={},
        )

        markdown = generate_markdown_report(report)

        assert "# Memory Injection Baseline Metrics Report" in markdown
        assert "*No metrics data found for the specified period.*" in markdown

    def test_report_with_single_variant(self):
        """Test report generation with single variant data."""
        metrics = VariantMetrics(
            variant="BASELINE",
            total_injections=100,
            successful_tasks=80,
            failed_tasks=20,
            unknown_outcome=0,
            total_retries=10,
            avg_latency_ms=50.0,
            avg_tokens=200,
            avg_mandates=3.0,
            avg_guardrails=2.0,
            avg_references=5.0,
            citation_rate=0.6,
            total_memories_loaded=100,
            total_memories_cited=60,
        )

        report = BaselineReport(
            start_date=datetime.now(UTC) - timedelta(days=7),
            end_date=datetime.now(UTC),
            total_injections=100,
            variant_metrics={"BASELINE": metrics},
            daily_counts={"2026-01-20": 50, "2026-01-21": 50},
            query_distribution={},
        )

        markdown = generate_markdown_report(report)

        # Check header
        assert "# Memory Injection Baseline Metrics Report" in markdown
        assert "**Total Injections:** 100" in markdown

        # Check summary table
        assert "| BASELINE |" in markdown
        assert "80.0%" in markdown  # Success rate
        assert "50ms" in markdown  # Latency
        assert "200" in markdown  # Tokens

        # Check detailed section
        assert "### BASELINE" in markdown
        assert "80 success" in markdown
        assert "20 failed" in markdown

        # Check daily breakdown
        assert "2026-01-20" in markdown
        assert "2026-01-21" in markdown

    def test_report_with_multiple_variants(self):
        """Test report generation with multiple variants."""
        baseline = VariantMetrics(
            variant="BASELINE",
            total_injections=50,
            successful_tasks=40,
            failed_tasks=10,
            unknown_outcome=0,
            total_retries=5,
            avg_latency_ms=50.0,
            avg_tokens=200,
            avg_mandates=3.0,
            avg_guardrails=2.0,
            avg_references=5.0,
            citation_rate=0.6,
            total_memories_loaded=50,
            total_memories_cited=30,
        )

        enhanced = VariantMetrics(
            variant="ENHANCED",
            total_injections=30,
            successful_tasks=28,
            failed_tasks=2,
            unknown_outcome=0,
            total_retries=2,
            avg_latency_ms=60.0,
            avg_tokens=250,
            avg_mandates=4.0,
            avg_guardrails=3.0,
            avg_references=6.0,
            citation_rate=0.8,
            total_memories_loaded=30,
            total_memories_cited=24,
        )

        report = BaselineReport(
            start_date=datetime.now(UTC) - timedelta(days=7),
            end_date=datetime.now(UTC),
            total_injections=80,
            variant_metrics={"BASELINE": baseline, "ENHANCED": enhanced},
            daily_counts={},
            query_distribution={},
        )

        markdown = generate_markdown_report(report)

        # Both variants should appear
        assert "| BASELINE |" in markdown
        assert "| ENHANCED |" in markdown
        assert "### BASELINE" in markdown
        assert "### ENHANCED" in markdown

    def test_report_includes_recommendations(self):
        """Test report includes data-driven recommendations."""
        metrics = VariantMetrics(
            variant="BASELINE",
            total_injections=100,
            successful_tasks=80,
            failed_tasks=20,
            unknown_outcome=0,
            total_retries=10,
            avg_latency_ms=50.0,
            avg_tokens=200,
            avg_mandates=3.0,
            avg_guardrails=2.0,
            avg_references=5.0,
            citation_rate=0.3,  # Low citation rate
            total_memories_loaded=100,
            total_memories_cited=30,
        )

        report = BaselineReport(
            start_date=datetime.now(UTC) - timedelta(days=7),
            end_date=datetime.now(UTC),
            total_injections=100,
            variant_metrics={"BASELINE": metrics},
            daily_counts={},
            query_distribution={},
        )

        markdown = generate_markdown_report(report)

        assert "## Recommendations" in markdown
        # Should flag low citation rate
        assert "Low Citation Rate Alert" in markdown

    def test_report_format_is_valid_markdown(self):
        """Test that report is valid markdown with tables."""
        metrics = VariantMetrics(
            variant="BASELINE",
            total_injections=100,
            successful_tasks=80,
            failed_tasks=20,
            unknown_outcome=0,
            total_retries=10,
            avg_latency_ms=50.0,
            avg_tokens=200,
            avg_mandates=3.0,
            avg_guardrails=2.0,
            avg_references=5.0,
            citation_rate=0.6,
            total_memories_loaded=100,
            total_memories_cited=60,
        )

        report = BaselineReport(
            start_date=datetime.now(UTC) - timedelta(days=7),
            end_date=datetime.now(UTC),
            total_injections=100,
            variant_metrics={"BASELINE": metrics},
            daily_counts={},
            query_distribution={},
        )

        markdown = generate_markdown_report(report)

        # Check markdown structure
        lines = markdown.split("\n")

        # Should have headers
        headers = [l for l in lines if l.startswith("#")]
        assert len(headers) >= 3

        # Should have table separators
        table_seps = [l for l in lines if "|---" in l]
        assert len(table_seps) >= 1

        # Should end with timestamp
        assert "Report generated at" in lines[-1]
