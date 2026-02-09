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
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from metrics.collector import collect_metrics
from metrics.models import BaselineReport, VariantMetrics, calculate_citation_rate
from metrics.reporter import generate_markdown_report

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Re-export for backward compatibility with tests
__all__ = [
    "BaselineReport",
    "VariantMetrics",
    "calculate_citation_rate",
    "generate_markdown_report",
]


def _print_dry_run_info(args: argparse.Namespace) -> None:
    """Print dry-run information."""
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


def _write_output(markdown: str, output_path: str | None) -> None:
    """Write markdown report to file or stdout."""
    if output_path:
        path = Path(output_path)
        path.write_text(markdown)
        logger.info("Report written to %s", path)
    else:
        print(markdown)


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
        _print_dry_run_info(args)
        return

    try:
        report = await collect_metrics(days=args.days)
        markdown = generate_markdown_report(report)
        _write_output(markdown, args.output)

    except Exception as e:
        logger.error("Failed to collect metrics: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
