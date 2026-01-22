#!/usr/bin/env python3
"""
Entity inventory script for Agent Hub Graphiti database.

Analyzes entities to identify:
- Total entity count by name
- Duplicate entities (same name, different UUIDs)
- Entity distribution by group_id
- Orphaned entities (no edges)

Usage:
    python -m scripts.memory.inventory
    python -m scripts.memory.inventory --duplicates
    python -m scripts.memory.inventory --export inventory.json
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


async def inventory_entities(show_duplicates: bool = False) -> dict:
    """
    Create an inventory of entities in the Graphiti database.

    Args:
        show_duplicates: Include detailed duplicate analysis

    Returns:
        Inventory results dict
    """
    graphiti = get_graphiti()
    driver = graphiti.driver

    logger.info("Starting entity inventory...")

    # Get all entities
    entity_query = """
    MATCH (e:EntityNode)
    RETURN e.uuid AS uuid, e.name AS name, e.summary AS summary,
           e.entity_type AS entity_type, e.created_at AS created_at,
           e.group_id AS group_id
    ORDER BY e.name, e.created_at
    """
    entity_records, _, _ = await driver.execute_query(entity_query)

    # Analyze entities
    entity_by_name = defaultdict(list)
    group_stats = defaultdict(int)
    total_entities = 0

    for record in entity_records:
        total_entities += 1
        name = record["name"] or "unnamed"
        group_id = record["group_id"] or "none"

        entity_by_name[name].append(
            {
                "uuid": record["uuid"],
                "group_id": group_id,
                "entity_type": record["entity_type"],
                "created_at": (
                    record["created_at"].to_native().isoformat()
                    if hasattr(record["created_at"], "to_native")
                    else str(record["created_at"])
                ),
                "summary": record["summary"] or "",
            }
        )

        group_stats[group_id] += 1

    # Identify duplicates
    duplicates = {}
    for name, entities in entity_by_name.items():
        if len(entities) > 1:
            duplicates[name] = {
                "count": len(entities),
                "group_distribution": defaultdict(int),
                "entities": entities if show_duplicates else [],
            }

            for entity in entities:
                duplicates[name]["group_distribution"][entity["group_id"]] += 1

    # Count deduplication opportunities
    dedup_savings = sum(count - 1 for name, info in duplicates.items() for count in [info["count"]])

    # Get edge count per entity
    edge_query = """
    MATCH (e:EntityEdge)
    RETURN e.uuid AS uuid
    """
    edge_records, _, _ = await driver.execute_query(edge_query)
    total_edges = len(edge_records)

    # Build inventory report
    inventory_report = {
        "inventory_date": datetime.now(UTC).isoformat(),
        "total_entities": total_entities,
        "unique_entity_names": len(entity_by_name),
        "total_edges": total_edges,
        "duplicate_names": len(duplicates),
        "deduplication_savings": dedup_savings,
        "entity_distribution_by_group": dict(group_stats),
        "top_duplicates": {},
    }

    # Add top 20 duplicates
    top_dupes = sorted(duplicates.items(), key=lambda x: x[1]["count"], reverse=True)[:20]
    for name, info in top_dupes:
        inventory_report["top_duplicates"][name] = {
            "count": info["count"],
            "groups": dict(info["group_distribution"]),
        }

    if show_duplicates:
        inventory_report["all_duplicates"] = duplicates

    await graphiti.close()
    return inventory_report


async def main():
    parser = argparse.ArgumentParser(description="Inventory entities in Graphiti database")
    parser.add_argument(
        "--duplicates",
        action="store_true",
        help="Include detailed duplicate analysis",
    )
    parser.add_argument("--export", help="Export inventory to JSON file")

    args = parser.parse_args()

    # Run inventory
    inventory_report = await inventory_entities(show_duplicates=args.duplicates)

    # Display summary
    print("\n" + "=" * 60)
    print("ENTITY INVENTORY REPORT")
    print("=" * 60)
    print(f"Total Entities: {inventory_report['total_entities']}")
    print(f"Unique Names: {inventory_report['unique_entity_names']}")
    print(f"Total Edges: {inventory_report['total_edges']}")
    print(f"Duplicate Names: {inventory_report['duplicate_names']}")
    print(
        f"Deduplication Potential: {inventory_report['deduplication_savings']} entities can be merged"
    )

    print("\nEntity Distribution by Group:")
    for group_id, count in sorted(
        inventory_report["entity_distribution_by_group"].items(),
        key=lambda x: x[1],
        reverse=True,
    ):
        print(f"  {group_id}: {count} entities")

    if inventory_report["top_duplicates"]:
        print(f"\nTop Duplicates (showing up to 20):")
        for name, info in list(inventory_report["top_duplicates"].items()):
            print(f"\n  {name}: {info['count']} instances")
            print(f"    Groups: {dict(info['groups'])}")

    # Export if requested
    if args.export:
        with open(args.export, "w") as f:
            json.dump(inventory_report, f, indent=2)
        print(f"\nInventory exported to: {args.export}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
