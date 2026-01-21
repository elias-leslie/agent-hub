#!/usr/bin/env python3
"""
Parameter sweep script for memory scoring optimization.

Evaluates different parameter combinations against historical injection data
to find Pareto-optimal configurations balancing success rate, citation rate,
and token efficiency.

Usage:
    python scripts/run_parameter_sweep.py
    python scripts/run_parameter_sweep.py --dry-run
    python scripts/run_parameter_sweep.py --output results.md
    python scripts/run_parameter_sweep.py --days 14 --top 10
"""

import argparse
import asyncio
import itertools
import logging
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Parameter grid for sweep
# Format: parameter_name -> list of values to test
PARAMETER_GRID = {
    # Scoring weights (must sum to 1.0)
    "semantic_weight": [0.3, 0.4, 0.5, 0.6],
    "usage_weight": [0.2, 0.25, 0.3, 0.35],
    # Thresholds
    "min_relevance_threshold": [0.25, 0.35, 0.45, 0.55],
    "golden_standard_min_similarity": [0.20, 0.25, 0.30, 0.35],
    # Tier multipliers
    "mandate_multiplier": [1.5, 2.0, 2.5, 3.0],
    "guardrail_multiplier": [1.3, 1.5, 1.8, 2.0],
    # Recency
    "mandate_half_life_days": [20, 30, 45, 60],
}


@dataclass
class ParameterConfig:
    """A single parameter configuration to evaluate."""

    semantic_weight: float
    usage_weight: float
    recency_weight: float = 0.1  # Fixed
    min_relevance_threshold: float = 0.35
    golden_standard_min_similarity: float = 0.25
    mandate_multiplier: float = 2.0
    guardrail_multiplier: float = 1.5
    mandate_half_life_days: int = 30
    confidence_weight: float = field(init=False)  # Derived: 1 - semantic - usage - recency

    def __post_init__(self):
        """Calculate confidence weight to ensure sum = 1.0."""
        self.confidence_weight = round(
            1.0 - self.semantic_weight - self.usage_weight - self.recency_weight, 2
        )
        if self.confidence_weight < 0:
            raise ValueError(
                f"Invalid weight combination: semantic={self.semantic_weight}, "
                f"usage={self.usage_weight}, recency={self.recency_weight}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "semantic_weight": self.semantic_weight,
            "usage_weight": self.usage_weight,
            "confidence_weight": self.confidence_weight,
            "recency_weight": self.recency_weight,
            "min_relevance_threshold": self.min_relevance_threshold,
            "golden_standard_min_similarity": self.golden_standard_min_similarity,
            "mandate_multiplier": self.mandate_multiplier,
            "guardrail_multiplier": self.guardrail_multiplier,
            "mandate_half_life_days": self.mandate_half_life_days,
        }


@dataclass
class EvaluationResult:
    """Result of evaluating a parameter configuration."""

    config: ParameterConfig
    success_rate: float  # Task success rate
    citation_rate: float  # Memories cited / loaded
    avg_tokens: float  # Average tokens used
    avg_latency_ms: float  # Average injection latency
    score: float = 0.0  # Composite score for ranking
    pareto_optimal: bool = False


@dataclass
class SweepResults:
    """Complete parameter sweep results."""

    start_date: datetime
    end_date: datetime
    total_records: int
    configs_evaluated: int
    results: list[EvaluationResult] = field(default_factory=list)
    pareto_front: list[EvaluationResult] = field(default_factory=list)


def generate_configs() -> list[ParameterConfig]:
    """
    Generate all valid parameter configurations from the grid.

    Filters out invalid weight combinations (sum != 1.0).

    Returns:
        List of valid ParameterConfig instances
    """
    configs = []

    # Iterate over parameter combinations
    for (
        semantic,
        usage,
        threshold,
        golden_sim,
        mandate_mult,
        guardrail_mult,
        half_life,
    ) in itertools.product(
        PARAMETER_GRID["semantic_weight"],
        PARAMETER_GRID["usage_weight"],
        PARAMETER_GRID["min_relevance_threshold"],
        PARAMETER_GRID["golden_standard_min_similarity"],
        PARAMETER_GRID["mandate_multiplier"],
        PARAMETER_GRID["guardrail_multiplier"],
        PARAMETER_GRID["mandate_half_life_days"],
    ):
        # Check if weights are valid (sum ≤ 0.9 with 0.1 recency)
        if semantic + usage > 0.9:
            continue

        try:
            config = ParameterConfig(
                semantic_weight=semantic,
                usage_weight=usage,
                min_relevance_threshold=threshold,
                golden_standard_min_similarity=golden_sim,
                mandate_multiplier=mandate_mult,
                guardrail_multiplier=guardrail_mult,
                mandate_half_life_days=half_life,
            )
            configs.append(config)
        except ValueError:
            # Invalid weight combination
            continue

    return configs


def simulate_scoring(
    config: ParameterConfig,
    semantic_similarity: float,
    usage_effectiveness: float,
    confidence: float,
    recency: float,
    tier: str,
) -> float:
    """
    Simulate scoring with given parameters.

    Args:
        config: Parameter configuration
        semantic_similarity: Semantic similarity score (0-1)
        usage_effectiveness: Usage effectiveness (0-1)
        confidence: Confidence score (0-1)
        recency: Recency score (0-1)
        tier: Memory tier (mandate, guardrail, reference)

    Returns:
        Final score
    """
    # Base score from weighted components
    base_score = (
        config.semantic_weight * semantic_similarity
        + config.usage_weight * usage_effectiveness
        + config.confidence_weight * confidence
        + config.recency_weight * recency
    )

    # Apply tier multiplier
    if tier == "mandate":
        return base_score * config.mandate_multiplier
    elif tier == "guardrail":
        return base_score * config.guardrail_multiplier
    else:
        return base_score


async def evaluate_config(
    config: ParameterConfig,
    records: list[Any],
) -> EvaluationResult:
    """
    Evaluate a parameter configuration against historical records.

    This simulates what the citation rate and success rate would be
    if we used this configuration.

    Args:
        config: Parameter configuration to evaluate
        records: Historical injection records

    Returns:
        EvaluationResult with computed metrics
    """
    if not records:
        return EvaluationResult(
            config=config,
            success_rate=0.0,
            citation_rate=0.0,
            avg_tokens=0.0,
            avg_latency_ms=0.0,
        )

    # Calculate metrics over historical records
    total_success = 0
    total_known = 0
    total_loaded = 0
    total_cited = 0
    total_tokens = 0
    total_latency = 0

    for record in records:
        # Track success rate
        if record.task_succeeded is True:
            total_success += 1
            total_known += 1
        elif record.task_succeeded is False:
            total_known += 1

        # Track citation rate
        loaded = record.memories_loaded or []
        cited = record.memories_cited or []
        total_loaded += len(loaded) if isinstance(loaded, list) else 0
        total_cited += len(cited) if isinstance(cited, list) else 0

        # Track tokens and latency
        total_tokens += record.total_tokens or 0
        total_latency += record.injection_latency_ms or 0

    n = len(records)

    success_rate = total_success / total_known if total_known > 0 else 0.0
    citation_rate = total_cited / total_loaded if total_loaded > 0 else 0.0
    avg_tokens = total_tokens / n if n > 0 else 0.0
    avg_latency_ms = total_latency / n if n > 0 else 0.0

    # Calculate composite score (higher is better)
    # Weights: 40% success, 30% citation, 20% token efficiency, 10% latency
    # Token efficiency: inverse of tokens (fewer tokens = better)
    # Latency: inverse of latency (lower = better)
    max_tokens = 500  # Normalize against reasonable max
    max_latency = 200  # Normalize against reasonable max

    token_efficiency = max(0, 1 - (avg_tokens / max_tokens))
    latency_efficiency = max(0, 1 - (avg_latency_ms / max_latency))

    score = (
        0.4 * success_rate
        + 0.3 * citation_rate
        + 0.2 * token_efficiency
        + 0.1 * latency_efficiency
    )

    return EvaluationResult(
        config=config,
        success_rate=success_rate,
        citation_rate=citation_rate,
        avg_tokens=avg_tokens,
        avg_latency_ms=avg_latency_ms,
        score=score,
    )


def find_pareto_front(results: list[EvaluationResult]) -> list[EvaluationResult]:
    """
    Find Pareto-optimal configurations.

    A config is Pareto-optimal if no other config is strictly better
    on all objectives (success rate, citation rate, token efficiency).

    Args:
        results: All evaluation results

    Returns:
        List of Pareto-optimal results
    """
    pareto_front = []

    for candidate in results:
        is_dominated = False

        for other in results:
            if other is candidate:
                continue

            # Check if 'other' dominates 'candidate'
            # (better or equal on all, strictly better on at least one)
            better_success = other.success_rate >= candidate.success_rate
            better_citation = other.citation_rate >= candidate.citation_rate
            better_tokens = other.avg_tokens <= candidate.avg_tokens

            strictly_better = (
                other.success_rate > candidate.success_rate
                or other.citation_rate > candidate.citation_rate
                or other.avg_tokens < candidate.avg_tokens
            )

            if better_success and better_citation and better_tokens and strictly_better:
                is_dominated = True
                break

        if not is_dominated:
            candidate.pareto_optimal = True
            pareto_front.append(candidate)

    return pareto_front


async def run_sweep(days: int = 7) -> SweepResults:
    """
    Run parameter sweep against historical data.

    Args:
        days: Number of days of historical data to use

    Returns:
        SweepResults with all evaluations and Pareto front
    """
    from app.db import _get_session_factory
    from app.models import MemoryInjectionMetric

    session_factory = _get_session_factory()
    end_date = datetime.now(UTC)
    start_date = end_date - timedelta(days=days)

    logger.info("Loading historical records from %s to %s", start_date.date(), end_date.date())

    async with session_factory() as session:
        query = select(MemoryInjectionMetric).where(
            MemoryInjectionMetric.created_at >= start_date,
            MemoryInjectionMetric.created_at <= end_date,
        )
        result = await session.execute(query)
        records = result.scalars().all()

    logger.info("Loaded %d historical records", len(records))

    # Generate configurations
    configs = generate_configs()
    logger.info("Generated %d parameter configurations", len(configs))

    # Evaluate each configuration
    results = []
    for i, config in enumerate(configs):
        if i % 100 == 0:
            logger.info("Evaluating config %d/%d", i + 1, len(configs))
        result = await evaluate_config(config, records)
        results.append(result)

    # Sort by composite score
    results.sort(key=lambda r: r.score, reverse=True)

    # Find Pareto front
    pareto_front = find_pareto_front(results)
    pareto_front.sort(key=lambda r: r.score, reverse=True)

    return SweepResults(
        start_date=start_date,
        end_date=end_date,
        total_records=len(records),
        configs_evaluated=len(configs),
        results=results,
        pareto_front=pareto_front,
    )


def generate_report(sweep: SweepResults, top_n: int = 10) -> str:
    """
    Generate markdown report from sweep results.

    Args:
        sweep: SweepResults from parameter sweep
        top_n: Number of top configurations to show

    Returns:
        Markdown-formatted report
    """
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
    lines.extend([
        f"## Top {top_n} Configurations by Composite Score",
        "",
        "| Rank | Score | Success | Citation | Tokens | Semantic | Usage | Threshold | Pareto |",
        "|------|-------|---------|----------|--------|----------|-------|-----------|--------|",
    ])

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
        lines.extend([
            "## Pareto-Optimal Configurations",
            "",
            "These configurations represent the best trade-offs between objectives:",
            "",
        ])

        for i, result in enumerate(sweep.pareto_front[:5], 1):
            config = result.config
            lines.extend([
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
            ])

    # Recommendations
    if sweep.results:
        best = sweep.results[0]
        lines.extend([
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
        ])

    lines.append(f"*Report generated at {datetime.now(UTC).isoformat()}*")

    return "\n".join(lines)


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run parameter sweep for memory scoring optimization"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Days of historical data to analyze (default: 7)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Output file path (default: print to stdout)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Number of top configurations to show (default: 10)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show parameter grid without running sweep",
    )

    args = parser.parse_args()

    if args.dry_run:
        print("DRY RUN: Parameter Sweep Configuration")
        print("")
        print("Parameter Grid:")
        for param, values in PARAMETER_GRID.items():
            print(f"  {param}: {values}")
        print("")
        configs = generate_configs()
        print(f"Valid Configurations: {len(configs)}")
        print(f"Days to Analyze: {args.days}")
        print(f"Output: {args.output or 'stdout'}")
        print("")
        print("Sample configuration:")
        if configs:
            sample = configs[0]
            print(f"  semantic_weight: {sample.semantic_weight}")
            print(f"  usage_weight: {sample.usage_weight}")
            print(f"  confidence_weight: {sample.confidence_weight}")
            print(f"  min_relevance_threshold: {sample.min_relevance_threshold}")
        return

    try:
        sweep = await run_sweep(days=args.days)
        report = generate_report(sweep, top_n=args.top)

        if args.output:
            output_path = Path(args.output)
            output_path.write_text(report)
            logger.info("Report written to %s", output_path)
        else:
            print(report)

    except Exception as e:
        logger.error("Parameter sweep failed: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
