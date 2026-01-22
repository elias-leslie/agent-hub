#!/usr/bin/env python3
"""
Consolidate duplicate entities script.

Consolidates duplicate entities in the global group based on inventory results.

Usage:
    # Consolidate specific entities
    python -m scripts.memory.consolidate_duplicates --entities "Assistant,ruff,User,F401"

    # Consolidate all duplicates (from inventory)
    python -m scripts.memory.consolidate_duplicates --all

    # Dry run (show what would be consolidated)
    python -m scripts.memory.consolidate_duplicates --all --dry-run
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.memory.consolidation_entities import (
    bulk_consolidate_entities,
    find_duplicate_entities,
)
from app.services.memory.graphiti_client import get_graphiti

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def find_all_duplicates(group_id: str = "global") -> list[str]:
    """
    Find all entity names that have duplicates in the specified group.

    Args:
        group_id: Group ID to search in

    Returns:
        List of entity names that have duplicates
    """
    graphiti = get_graphiti()
    driver = graphiti.driver

    query = """
    MATCH (e:EntityNode {group_id: $group_id})
    WITH e.name AS name, count(e) AS count
    WHERE count > 1
    RETURN name, count
    ORDER BY count DESC
    """
    records, _, _ = await driver.execute_query(query, group_id=group_id)

    duplicates = [record["name"] for record in records]
    await graphiti.close()

    return duplicates


async def consolidate_entities(
    entity_names: list[str],
    group_id: str = "global",
    dry_run: bool = False,
) -> dict:
    """
    Consolidate entities.

    Args:
        entity_names: List of entity names to consolidate
        group_id: Group ID to consolidate within
        dry_run: If True, only show what would be consolidated

    Returns:
        Consolidation results
    """
    graphiti = get_graphiti()
    driver = graphiti.driver

    if dry_run:
        print("\nDRY RUN - No changes will be made")
        print("=" * 60)

        for entity_name in entity_names:
            duplicates = await find_duplicate_entities(driver, entity_name, group_id)
            if len(duplicates) > 1:
                print(f"\n{entity_name}: {len(duplicates)} instances")
                for dup in duplicates:
                    created_at = dup["created_at"]
                    if hasattr(created_at, "to_native"):
                        created_at = created_at.to_native().isoformat()[:10]
                    print(f"  - {dup['uuid'][:8]} (created: {created_at})")
                print(f"  -> Would merge into oldest: {duplicates[0]['uuid'][:8]}")

        await graphiti.close()
        return {"dry_run": True}

    # Perform actual consolidation
    logger.info("Consolidating %d entities in group '%s'", len(entity_names), group_id)
    results = await bulk_consolidate_entities(driver, entity_names, group_id)

    await graphiti.close()
    return results


async def main():
    parser = argparse.ArgumentParser(description="Consolidate duplicate entities")
    parser.add_argument(
        "--entities",
        help="Comma-separated list of entity names to consolidate",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Consolidate all duplicates found in the group",
    )
    parser.add_argument(
        "--group",
        default="global",
        help="Group ID to consolidate within (default: global)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be consolidated without making changes",
    )

    args = parser.parse_args()

    if args.entities:
        entity_names = [name.strip() for name in args.entities.split(",")]
    elif args.all:
        logger.info("Finding all duplicates in group '%s'", args.group)
        entity_names = await find_all_duplicates(args.group)
        logger.info("Found %d entity names with duplicates", len(entity_names))
    else:
        parser.print_help()
        return

    if not entity_names:
        print("No entities to consolidate")
        return

    results = await consolidate_entities(entity_names, args.group, args.dry_run)

    if not args.dry_run:
        print("\nConsolidation Results:")
        print("=" * 60)
        print(f"Total processed: {results['total_processed']}")
        print(f"Total entities merged: {results['total_consolidated']}")
        print(f"Total edges updated: {results['total_edges_updated']}")

        if results["failed"]:
            print(f"\nFailed: {len(results['failed'])}")
            for failure in results["failed"]:
                print(f"  - {failure['entity_name']}: {failure['error']}")

        if results["details"]:
            print("\nSuccessfully consolidated:")
            for detail in results["details"]:
                print(f"  - {detail['entity_name']}: {detail['merged_count']} duplicates merged")


if __name__ == "__main__":
    asyncio.run(main())
