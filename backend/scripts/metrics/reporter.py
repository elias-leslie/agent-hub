"""Report generation for baseline metrics."""

from datetime import UTC, datetime

from metrics.models import BaselineReport


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
    lines.extend(_build_summary_table(report))
    lines.append("")

    # Detailed metrics per variant
    lines.extend(_build_detailed_analysis(report))

    # Daily breakdown
    if report.daily_counts:
        lines.extend(_build_daily_breakdown(report))

    # Recommendations
    lines.extend(_build_recommendations(report))

    lines.append("")
    lines.append(f"*Report generated at {datetime.now(UTC).isoformat()}*")

    return "\n".join(lines)


def _build_summary_table(report: BaselineReport) -> list[str]:
    """Build summary table section."""
    lines = [
        "| Variant | Injections | Success Rate | Retry Rate | Avg Latency | Avg Tokens | Citation Rate |",
        "|---------|------------|--------------|------------|-------------|------------|---------------|",
    ]

    for variant, metrics in sorted(report.variant_metrics.items()):
        lines.append(
            f"| {variant} | {metrics.total_injections} | "
            f"{metrics.success_rate:.1%} | {metrics.retry_rate:.2f} | "
            f"{metrics.avg_latency_ms:.0f}ms | {metrics.avg_tokens} | "
            f"{metrics.citation_rate:.1%} |"
        )

    return lines


def _build_detailed_analysis(report: BaselineReport) -> list[str]:
    """Build detailed variant analysis section."""
    lines = ["## Detailed Variant Analysis", ""]

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

    return lines


def _build_daily_breakdown(report: BaselineReport) -> list[str]:
    """Build daily breakdown section."""
    lines = [
        "## Daily Injection Volume",
        "",
        "| Date | Injections |",
        "|------|------------|",
    ]

    for date_str in sorted(report.daily_counts.keys()):
        lines.append(f"| {date_str} | {report.daily_counts[date_str]} |")

    lines.append("")
    return lines


def _build_recommendations(report: BaselineReport) -> list[str]:
    """Build recommendations section."""
    lines = [
        "## Recommendations",
        "",
        "Based on the baseline metrics:",
        "",
    ]

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

    return lines
