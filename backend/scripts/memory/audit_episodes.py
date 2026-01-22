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
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.memory.graphiti_client import get_graphiti

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def audit_episodes(group_filter: str | None = None, verbose: bool = False) -> dict:
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

    # Get all episodes with group stats
    if group_filter:
        query = """
        MATCH (e:Episodic {group_id: $group_id})
        RETURN e.uuid AS uuid, e.name AS name, e.content AS content,
               e.group_id AS group_id, e.created_at AS created_at,
               e.source_description AS source_description,
               e.entity_edges AS entity_edges
        ORDER BY e.created_at DESC
        """
        records, _, _ = await driver.execute_query(query, group_id=group_filter)
    else:
        query = """
        MATCH (e:Episodic)
        RETURN e.uuid AS uuid, e.name AS name, e.content AS content,
               e.group_id AS group_id, e.created_at AS created_at,
               e.source_description AS source_description,
               e.entity_edges AS entity_edges
        ORDER BY e.created_at DESC
        """
        records, _, _ = await driver.execute_query(query)

    # Analyze episodes
    group_stats = defaultdict(lambda: {"count": 0, "entity_count": 0, "episodes": []})
    verbose_patterns = []
    total_episodes = 0

    for record in records:
        total_episodes += 1
        group_id = record["group_id"] or "none"
        content = record["content"] or ""
        entity_edges = record["entity_edges"] or []

        # Group stats
        group_stats[group_id]["count"] += 1
        group_stats[group_id]["entity_count"] += len(entity_edges)

        if verbose:
            # Check for verbose patterns
            verbose_indicators = [
                "you should",
                "i recommend",
                "please",
                "thank you",
                "let me know",
                "feel free",
            ]

            if any(indicator in content.lower() for indicator in verbose_indicators):
                verbose_patterns.append(
                    {
                        "uuid": record["uuid"][:8],
                        "group_id": group_id,
                        "content_preview": content[:150],
                        "created_at": (
                            record["created_at"].to_native().isoformat()
                            if hasattr(record["created_at"], "to_native")
                            else str(record["created_at"])
                        ),
                    }
                )

        # Store episode details if requested
        if verbose and group_filter:
            group_stats[group_id]["episodes"].append(
                {
                    "uuid": record["uuid"][:8],
                    "name": record["name"],
                    "content_length": len(content),
                    "entity_count": len(entity_edges),
                    "created_at": (
                        record["created_at"].to_native().isoformat()
                        if hasattr(record["created_at"], "to_native")
                        else str(record["created_at"])
                    ),
                }
            )

    # Identify legacy groups
    legacy_groups = {}
    for group_id, stats in group_stats.items():
        if group_id.startswith(("user-", "test-", "session-")) or group_id in (
            "default",
            "none",
        ):
            legacy_groups[group_id] = stats

    # Build audit report
    audit_report = {
        "audit_date": datetime.now(UTC).isoformat(),
        "total_episodes": total_episodes,
        "total_groups": len(group_stats),
        "legacy_groups_count": len(legacy_groups),
        "group_distribution": {
            group_id: stats["count"] for group_id, stats in group_stats.items()
        },
        "entity_distribution": {
            group_id: stats["entity_count"] for group_id, stats in group_stats.items()
        },
        "legacy_groups": legacy_groups,
        "verbose_pattern_count": len(verbose_patterns),
    }

    if verbose:
        audit_report["verbose_patterns"] = verbose_patterns

    await graphiti.close()
    return audit_report


async def main():
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

    # Display summary
    print("\n" + "=" * 60)
    print("EPISODE AUDIT REPORT")
    print("=" * 60)
    print(f"Total Episodes: {audit_report['total_episodes']}")
    print(f"Total Groups: {audit_report['total_groups']}")
    print(f"Legacy Groups: {audit_report['legacy_groups_count']}")
    print(f"Verbose Patterns Detected: {audit_report['verbose_pattern_count']}")

    print("\nGroup Distribution:")
    for group_id, count in sorted(
        audit_report["group_distribution"].items(),
        key=lambda x: x[1],
        reverse=True,
    ):
        entity_count = audit_report["entity_distribution"].get(group_id, 0)
        legacy_marker = " [LEGACY]" if group_id in audit_report["legacy_groups"] else ""
        print(f"  {group_id}: {count} episodes, {entity_count} entities{legacy_marker}")

    if audit_report["legacy_groups"]:
        print("\nLegacy Groups Details:")
        for group_id, stats in audit_report["legacy_groups"].items():
            print(
                f"  {group_id}: {stats['count']} episodes, {stats['entity_count']} entities"
            )

    if args.verbose and audit_report.get("verbose_patterns"):
        print(f"\nVerbose Patterns Found ({len(audit_report['verbose_patterns'])}):")
        for pattern in audit_report["verbose_patterns"][:10]:  # Show first 10
            print(f"\n  UUID: {pattern['uuid']}")
            print(f"  Group: {pattern['group_id']}")
            print(f"  Created: {pattern['created_at']}")
            print(f"  Preview: {pattern['content_preview']}")

    # Export if requested
    if args.export:
        with open(args.export, "w") as f:
            json.dump(audit_report, f, indent=2)
        print(f"\nAudit report exported to: {args.export}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
