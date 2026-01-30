"""Report generation for parameter sweep results."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from backend.scripts.sweep_evaluation import EvaluationResult


@dataclass
class SweepResults:
    """Complete parameter sweep results."""

    start_date: datetime
    end_date: datetime
    total_records: int
    configs_evaluated: int
    results: list[EvaluationResult] = field(default_factory=list)
    pareto_front: list[EvaluationResult] = field(default_factory=list)


def generate_report(sweep: SweepResults, top_n: int = 10) -> str:
    """Generate markdown report from sweep results."""
    lines = [
        "# Parameter Sweep Results",
        "",
        f"**Period:** {sweep.start_date.date()} to {sweep.end_date.date()}",
        f"**Records Analyzed:** {sweep.total_records}",
        f"**Configurations Evaluated:** {sweep.configs_evaluated}",
        f"**Pareto-Optimal Configs:** {len(sweep.pareto_front)}",
        "",
    ]

    if not sweep.results:
        lines.append("*No results to display.*")
        return "\n".join(lines)

    # Top configurations
    lines.extend(
        [
            f"## Top {top_n} Configurations by Composite Score",
            "",
            "| Rank | Score | Success | Citation | Tokens | Semantic | Usage | Threshold | Pareto |",
            "|------|-------|---------|----------|--------|----------|-------|-----------|--------|",
        ]
    )

    for i, result in enumerate(sweep.results[:top_n], 1):
        pareto_mark = "✓" if result.pareto_optimal else ""
        lines.append(
            f"| {i} | {result.score:.3f} | {result.success_rate:.1%} | "
            f"{result.citation_rate:.1%} | {result.avg_tokens:.0f} | "
            f"{result.config.semantic_weight} | {result.config.usage_weight} | "
            f"{result.config.min_relevance_threshold} | {pareto_mark} |"
        )

    lines.append("")

    # Pareto-optimal configurations
    if sweep.pareto_front:
        lines.extend(
            [
                "## Pareto-Optimal Configurations",
                "",
                "These configurations represent the best trade-offs between objectives:",
                "",
            ]
        )

        for i, result in enumerate(sweep.pareto_front[:5], 1):
            config = result.config
            lines.extend(
                [
                    f"### Configuration {i}",
                    "",
                    "**Performance:**",
                    f"- Success Rate: {result.success_rate:.1%}",
                    f"- Citation Rate: {result.citation_rate:.1%}",
                    f"- Avg Tokens: {result.avg_tokens:.0f}",
                    f"- Avg Latency: {result.avg_latency_ms:.0f}ms",
                    "",
                    "**Parameters:**",
                    f"- Scoring Weights: semantic={config.semantic_weight}, usage={config.usage_weight}, "
                    f"confidence={config.confidence_weight}, recency={config.recency_weight}",
                    f"- Min Relevance Threshold: {config.min_relevance_threshold}",
                    f"- Golden Standard Min Similarity: {config.golden_standard_min_similarity}",
                    f"- Tier Multipliers: mandate={config.mandate_multiplier}, guardrail={config.guardrail_multiplier}",
                    f"- Mandate Half-Life: {config.mandate_half_life_days} days",
                    "",
                ]
            )

    # Recommendations
    if sweep.results:
        best = sweep.results[0]
        lines.extend(
            [
                "## Recommendations",
                "",
                f"**Best Overall Configuration (Score: {best.score:.3f}):**",
                "",
                "```python",
                "VariantConfig(",
                "    scoring_weights=ScoringWeights(",
                f"        semantic={best.config.semantic_weight},",
                f"        usage={best.config.usage_weight},",
                f"        confidence={best.config.confidence_weight},",
                f"        recency={best.config.recency_weight},",
                "    ),",
                f"    min_relevance_threshold={best.config.min_relevance_threshold},",
                f"    golden_standard_min_similarity={best.config.golden_standard_min_similarity},",
                "    tier_multipliers=TierMultipliers(",
                f"        mandate={best.config.mandate_multiplier},",
                f"        guardrail={best.config.guardrail_multiplier},",
                "    ),",
                "    recency_config=RecencyConfig(",
                f"        mandate_half_life_days={best.config.mandate_half_life_days},",
                "    ),",
                ")",
                "```",
                "",
            ]
        )

    lines.append(f"*Report generated at {datetime.now(UTC).isoformat()}*")
    return "\n".join(lines)
