#!/usr/bin/env python3
"""
Baseline metrics collection for memory system A/B testing.

Collects and analyzes injection metrics from the past week to establish
baseline measurements for comparison during optimization experiments.

Usage:
    python scripts/collect_baseline_metrics.py
    python scripts/collect_baseline_metrics.py --days 14 --output report.md
    python scripts/collect_baseline_metrics.py --dry-run
"""

import argparse
import asyncio
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class VariantMetrics:
    """Aggregated metrics for a single variant."""

    variant: str
    total_injections: int
    successful_tasks: int
    failed_tasks: int
    unknown_outcome: int
    total_retries: int
    avg_latency_ms: float
    avg_tokens: int
    avg_mandates: float
    avg_guardrails: float
    avg_references: float
    citation_rate: float  # memories_cited / memories_loaded
    total_memories_loaded: int
    total_memories_cited: int

    @property
    def success_rate(self) -> float:
        """Calculate task success rate."""
        total_known = self.successful_tasks + self.failed_tasks
        if total_known == 0:
            return 0.0
        return self.successful_tasks / total_known

    @property
    def retry_rate(self) -> float:
        """Calculate average retries per task."""
        if self.total_injections == 0:
            return 0.0
        return self.total_retries / self.total_injections


@dataclass
class BaselineReport:
    """Complete baseline metrics report."""

    start_date: datetime
    end_date: datetime
    total_injections: int
    variant_metrics: dict[str, VariantMetrics]
    daily_counts: dict[str, int]  # date_str -> count
    query_distribution: dict[str, int]  # query category -> count


def calculate_citation_rate(loaded: int, cited: int) -> float:
    """Calculate citation rate safely."""
    if loaded == 0:
        return 0.0
    return cited / loaded


async def collect_metrics(days: int = 7) -> BaselineReport:
    """
    Collect injection metrics from the database.

    Args:
        days: Number of days to look back

    Returns:
        BaselineReport with aggregated metrics
    """
    from app.db import _get_session_factory
    from app.models import MemoryInjectionMetric

    session_factory = _get_session_factory()
    end_date = datetime.now(UTC)
    start_date = end_date - timedelta(days=days)

    logger.info("Collecting metrics from %s to %s", start_date.date(), end_date.date())

    async with session_factory() as session:
        # Query all metrics in date range
        query = select(MemoryInjectionMetric).where(
            MemoryInjectionMetric.created_at >= start_date,
            MemoryInjectionMetric.created_at <= end_date,
        )
        result = await session.execute(query)
        records = result.scalars().all()

    logger.info("Found %d injection records", len(records))

    # Aggregate by variant
    variant_data: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "total": 0,
            "success": 0,
            "fail": 0,
            "unknown": 0,
            "retries": 0,
            "latency_sum": 0,
            "tokens_sum": 0,
            "mandates_sum": 0,
            "guardrails_sum": 0,
            "references_sum": 0,
            "loaded_sum": 0,
            "cited_sum": 0,
        }
    )

    daily_counts: dict[str, int] = defaultdict(int)

    for record in records:
        variant = record.variant or "BASELINE"
        data = variant_data[variant]

        data["total"] += 1

        if record.task_succeeded is True:
            data["success"] += 1
        elif record.task_succeeded is False:
            data["fail"] += 1
        else:
            data["unknown"] += 1

        data["retries"] += record.retries or 0
        data["latency_sum"] += record.injection_latency_ms or 0
        data["tokens_sum"] += record.total_tokens or 0
        data["mandates_sum"] += record.mandates_count or 0
        data["guardrails_sum"] += record.guardrails_count or 0
        data["references_sum"] += record.reference_count or 0

        # Count memories loaded and cited
        loaded = record.memories_loaded or []
        cited = record.memories_cited or []
        data["loaded_sum"] += len(loaded) if isinstance(loaded, list) else 0
        data["cited_sum"] += len(cited) if isinstance(cited, list) else 0

        # Daily counts
        date_str = record.created_at.date().isoformat()
        daily_counts[date_str] += 1

    # Build variant metrics
    variant_metrics: dict[str, VariantMetrics] = {}

    for variant, data in variant_data.items():
        total = data["total"]
        if total == 0:
            continue

        variant_metrics[variant] = VariantMetrics(
            variant=variant,
            total_injections=total,
            successful_tasks=data["success"],
            failed_tasks=data["fail"],
            unknown_outcome=data["unknown"],
            total_retries=data["retries"],
            avg_latency_ms=data["latency_sum"] / total if total > 0 else 0,
            avg_tokens=int(data["tokens_sum"] / total) if total > 0 else 0,
            avg_mandates=data["mandates_sum"] / total if total > 0 else 0,
            avg_guardrails=data["guardrails_sum"] / total if total > 0 else 0,
            avg_references=data["references_sum"] / total if total > 0 else 0,
            citation_rate=calculate_citation_rate(data["loaded_sum"], data["cited_sum"]),
            total_memories_loaded=data["loaded_sum"],
            total_memories_cited=data["cited_sum"],
        )

    return BaselineReport(
        start_date=start_date,
        end_date=end_date,
        total_injections=len(records),
        variant_metrics=variant_metrics,
        daily_counts=dict(daily_counts),
        query_distribution={},  # TODO: implement query categorization
    )


def generate_markdown_report(report: BaselineReport) -> str:
    """
    Generate a markdown report from collected metrics.

    Args:
        report: BaselineReport with aggregated data

    Returns:
        Markdown-formatted report string
    """
    lines = [
        "# Memory Injection Baseline Metrics Report",
        "",
        f"**Period:** {report.start_date.date()} to {report.end_date.date()}",
        f"**Total Injections:** {report.total_injections}",
        "",
        "## Summary by Variant",
        "",
    ]

    if not report.variant_metrics:
        lines.append("*No metrics data found for the specified period.*")
        return "\n".join(lines)

    # Summary table
    lines.extend(
        [
            "| Variant | Injections | Success Rate | Retry Rate | Avg Latency | Avg Tokens | Citation Rate |",
            "|---------|------------|--------------|------------|-------------|------------|---------------|",
        ]
    )

    for variant, metrics in sorted(report.variant_metrics.items()):
        lines.append(
            f"| {variant} | {metrics.total_injections} | "
            f"{metrics.success_rate:.1%} | {metrics.retry_rate:.2f} | "
            f"{metrics.avg_latency_ms:.0f}ms | {metrics.avg_tokens} | "
            f"{metrics.citation_rate:.1%} |"
        )

    lines.append("")

    # Detailed metrics per variant
    lines.append("## Detailed Variant Analysis")
    lines.append("")

    for variant, metrics in sorted(report.variant_metrics.items()):
        lines.extend(
            [
                f"### {variant}",
                "",
                f"- **Total Injections:** {metrics.total_injections}",
                f"- **Task Outcomes:** {metrics.successful_tasks} success, "
                f"{metrics.failed_tasks} failed, {metrics.unknown_outcome} unknown",
                f"- **Success Rate:** {metrics.success_rate:.1%}",
                f"- **Total Retries:** {metrics.total_retries} ({metrics.retry_rate:.2f} per task)",
                f"- **Avg Latency:** {metrics.avg_latency_ms:.0f}ms",
                f"- **Avg Tokens:** {metrics.avg_tokens}",
                "",
                "**Injection Counts:**",
                f"- Mandates: {metrics.avg_mandates:.1f} avg",
                f"- Guardrails: {metrics.avg_guardrails:.1f} avg",
                f"- References: {metrics.avg_references:.1f} avg",
                "",
                "**Citation Tracking:**",
                f"- Memories Loaded: {metrics.total_memories_loaded}",
                f"- Memories Cited: {metrics.total_memories_cited}",
                f"- Citation Rate: {metrics.citation_rate:.1%}",
                "",
            ]
        )

    # Daily breakdown
    if report.daily_counts:
        lines.extend(
            [
                "## Daily Injection Volume",
                "",
                "| Date | Injections |",
                "|------|------------|",
            ]
        )

        for date_str in sorted(report.daily_counts.keys()):
            lines.append(f"| {date_str} | {report.daily_counts[date_str]} |")

        lines.append("")

    # Recommendations
    lines.extend(
        [
            "## Recommendations",
            "",
            "Based on the baseline metrics:",
            "",
        ]
    )

    # Add data-driven recommendations
    if report.variant_metrics:
        best_variant = max(
            report.variant_metrics.values(),
            key=lambda m: m.success_rate if m.successful_tasks + m.failed_tasks > 0 else 0,
        )
        worst_citation = min(
            report.variant_metrics.values(),
            key=lambda m: m.citation_rate,
        )

        if best_variant.success_rate > 0:
            lines.append(
                f"1. **Best Success Rate:** {best_variant.variant} ({best_variant.success_rate:.1%})"
            )
        if worst_citation.citation_rate < 0.5:
            lines.append(
                f"2. **Low Citation Rate Alert:** {worst_citation.variant} "
                f"({worst_citation.citation_rate:.1%}) - consider tuning relevance threshold"
            )

    lines.append("")
    lines.append(f"*Report generated at {datetime.now(UTC).isoformat()}*")

    return "\n".join(lines)


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Collect baseline metrics for memory injection A/B testing"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to look back (default: 7)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Output file path (default: print to stdout)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be collected without database access",
    )

    args = parser.parse_args()

    if args.dry_run:
        print("DRY RUN: Would collect metrics from the following:")
        print(f"  Days: {args.days}")
        print(f"  Start: {(datetime.now(UTC) - timedelta(days=args.days)).date()}")
        print(f"  End: {datetime.now(UTC).date()}")
        print(f"  Output: {args.output or 'stdout'}")
        print("\nMetrics to collect:")
        print("  - Injection counts by variant")
        print("  - Task success/failure rates")
        print("  - Retry rates")
        print("  - Latency distributions")
        print("  - Token usage")
        print("  - Citation rates")
        return

    try:
        report = await collect_metrics(days=args.days)
        markdown = generate_markdown_report(report)

        if args.output:
            output_path = Path(args.output)
            output_path.write_text(markdown)
            logger.info("Report written to %s", output_path)
        else:
            print(markdown)

    except Exception as e:
        logger.error("Failed to collect metrics: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
