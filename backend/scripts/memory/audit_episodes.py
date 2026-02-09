#!/usr/bin/env python3
"""
Episode audit script for Agent Hub Graphiti database.

Analyzes episodes to identify:
- Legacy groups (user-*, test-*, default, etc.)
- Episode distribution by group_id
- Verbose content patterns (for validation improvement)
- Entity and edge distribution

Usage:
    python -m scripts.memory.audit_episodes
    python -m scripts.memory.audit_episodes --group user-123
    python -m scripts.memory.audit_episodes --verbose --export audit_report.json
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.memory.graphiti_client import get_graphiti
from scripts.memory.audit_analyzer import analyze_episodes
from scripts.memory.audit_queries import build_episode_query

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def audit_episodes(group_filter: str | None = None, verbose: bool = False) -> dict[str, Any]:
    """
    Audit episodes in the Graphiti database.

    Args:
        group_filter: Optional group_id to filter by
        verbose: Include detailed content analysis

    Returns:
        Audit results dict
    """
    graphiti = get_graphiti()
    driver = graphiti.driver

    logger.info("Starting episode audit...")

    # Execute query
    query, params = build_episode_query(group_filter)
    records, _, _ = await driver.execute_query(query, **params)

    # Analyze results
    include_episodes = verbose and group_filter is not None
    audit_report = analyze_episodes(records, verbose=verbose, include_episodes=include_episodes)

    await graphiti.close()
    return audit_report


async def main() -> None:
    """CLI entry point for episode auditing."""
    parser = argparse.ArgumentParser(description="Audit episodes in Graphiti database")
    parser.add_argument("--group", help="Filter by group_id")
    parser.add_argument("--verbose", action="store_true", help="Include detailed analysis")
    parser.add_argument("--export", help="Export audit report to JSON file")

    args = parser.parse_args()

    # Run audit
    audit_report = await audit_episodes(
        group_filter=args.group,
        verbose=args.verbose,
    )

    # Display and export
    from scripts.memory.audit_reporter import print_audit_summary

    print_audit_summary(audit_report, verbose=args.verbose)

    if args.export:
        with open(args.export, "w") as f:
            json.dump(audit_report, f, indent=2)
        print(f"\nAudit report exported to: {args.export}")


if __name__ == "__main__":
    asyncio.run(main())
