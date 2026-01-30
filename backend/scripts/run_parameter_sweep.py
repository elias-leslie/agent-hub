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
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.scripts.sweep_config import PARAMETER_GRID, generate_configs
from backend.scripts.sweep_evaluation import evaluate_config, find_pareto_front
from backend.scripts.sweep_report import SweepResults, generate_report
from sqlalchemy import select

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_sweep(days: int = 7) -> SweepResults:
    """Run parameter sweep against historical data."""
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

    configs = generate_configs()
    logger.info("Generated %d parameter configurations", len(configs))

    results = []
    for i, config in enumerate(configs):
        if i % 100 == 0:
            logger.info("Evaluating config %d/%d", i + 1, len(configs))
        result = await evaluate_config(config, records)
        results.append(result)

    results.sort(key=lambda r: r.score, reverse=True)
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


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Run parameter sweep for memory scoring optimization")
    parser.add_argument("--days", type=int, default=7, help="Days of historical data to analyze (default: 7)")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output file path (default: print to stdout)")
    parser.add_argument("--top", type=int, default=10, help="Number of top configurations to show (default: 10)")
    parser.add_argument("--dry-run", action="store_true", help="Show parameter grid without running sweep")
    args = parser.parse_args()

    if args.dry_run:
        print("DRY RUN: Parameter Sweep Configuration\n")
        print("Parameter Grid:")
        for param, values in PARAMETER_GRID.items():
            print(f"  {param}: {values}")
        configs = generate_configs()
        print(f"\nValid Configurations: {len(configs)}")
        print(f"Days to Analyze: {args.days}")
        print(f"Output: {args.output or 'stdout'}\n")
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
            Path(args.output).write_text(report)
            logger.info("Report written to %s", args.output)
        else:
            print(report)
    except Exception as e:
        logger.error("Parameter sweep failed: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
