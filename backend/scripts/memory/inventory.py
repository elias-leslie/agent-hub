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
from pathlib import Path

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.memory.graphiti_client import get_graphiti

from .inventory_helpers import (
    analyze_entity_records,
    build_inventory_report,
    display_report,
    find_duplicates,
)

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

    entity_query = """
    MATCH (e:Entity)
    RETURN e.uuid AS uuid, e.name AS name, e.summary AS summary,
           e.entity_type AS entity_type, e.created_at AS created_at,
           e.group_id AS group_id
    ORDER BY e.name, e.created_at
    """
    entity_records, _, _ = await driver.execute_query(entity_query)

    entity_by_name, group_stats, total_entities = analyze_entity_records(
        entity_records, show_duplicates
    )
    duplicates, dedup_savings = find_duplicates(entity_by_name, show_duplicates)

    edge_query = """
    MATCH (e:EntityEdge)
    RETURN e.uuid AS uuid
    """
    edge_records, _, _ = await driver.execute_query(edge_query)
    total_edges = len(edge_records)

    inventory_report = build_inventory_report(
        total_entities=total_entities,
        entity_by_name=entity_by_name,
        total_edges=total_edges,
        duplicates=duplicates,
        dedup_savings=dedup_savings,
        group_stats=group_stats,
        show_duplicates=show_duplicates,
    )

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

    inventory_report = await inventory_entities(show_duplicates=args.duplicates)

    display_report(inventory_report)

    if args.export:
        with open(args.export, "w") as f:
            json.dump(inventory_report, f, indent=2)
        print(f"\nInventory exported to: {args.export}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
