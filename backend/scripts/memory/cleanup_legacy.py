#!/usr/bin/env python3
"""
Legacy group cleanup script for Agent Hub Graphiti database.

Identifies and cleans up legacy groups (user-*, test-*, default, etc.)
according to the manual curation strategy:
1. Audit legacy groups
2. Manually review and curate valuable content
3. Delete the rest

Usage:
    # List legacy groups
    python -m scripts.memory.cleanup_legacy --list

    # Review episodes in a legacy group
    python -m scripts.memory.cleanup_legacy --review user-123

    # Delete a legacy group (with confirmation)
    python -m scripts.memory.cleanup_legacy --delete user-123

    # Delete all legacy groups (DESTRUCTIVE, requires confirmation)
    python -m scripts.memory.cleanup_legacy --delete-all
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.memory.graphiti_client import get_graphiti
from scripts.memory.cleanup_legacy_queries import (
    delete_group_data,
    get_group_episodes,
    get_group_stats,
)
from scripts.memory.cleanup_legacy_ui import (
    print_delete_all_result,
    print_delete_result,
    print_group_review,
    print_legacy_groups_list,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def list_legacy_groups() -> list[dict]:
    """List all legacy groups with episode and entity counts."""
    graphiti = get_graphiti()
    group_stats = await get_group_stats(graphiti)
    legacy_groups = [
        {"group_id": gid, **stats}
        for gid, stats in sorted(
            group_stats.items(),
            key=lambda x: x[1]["entity_count"] + x[1]["episode_count"],
            reverse=True,
        )
    ]
    await graphiti.close()
    return legacy_groups


async def review_group(group_id: str) -> None:
    """Review episodes in a legacy group."""
    graphiti = get_graphiti()
    episodes = await get_group_episodes(graphiti, group_id, limit=50)
    print_group_review(group_id, episodes)
    await graphiti.close()


async def delete_group(group_id: str, confirm: bool = False) -> dict:
    """Delete all episodes and entities in a legacy group."""
    if not confirm:
        logger.error("Deletion must be confirmed with --confirm flag")
        return {"deleted_episodes": 0, "deleted_entities": 0, "success": False}

    graphiti = get_graphiti()
    logger.warning("Deleting group: %s", group_id)
    deletion_stats = await delete_group_data(graphiti, group_id)
    logger.info(
        "Deleted group %s: %d episodes, %d entities, %d edges",
        group_id,
        deletion_stats["deleted_episodes"],
        deletion_stats["deleted_entities"],
        deletion_stats["deleted_edges"],
    )
    await graphiti.close()
    return {"group_id": group_id, **deletion_stats, "success": True}


async def delete_all_legacy_groups(confirm: bool = False) -> dict:
    """Delete all legacy groups."""
    if not confirm:
        logger.error("Deletion must be confirmed")
        return {"total_groups": 0, "deleted_groups": 0, "success": False}

    legacy_groups = await list_legacy_groups()
    logger.warning("Deleting %d legacy groups", len(legacy_groups))
    results = {
        "total_groups": len(legacy_groups),
        "deleted_groups": 0,
        "total_episodes": 0,
        "total_entities": 0,
        "details": [],
    }

    for group in legacy_groups:
        result = await delete_group(group["group_id"], confirm=True)
        if result["success"]:
            results["deleted_groups"] += 1
            results["total_episodes"] += result["deleted_episodes"]
            results["total_entities"] += result["deleted_entities"]
            results["details"].append(result)

    logger.info(
        "Deleted %d legacy groups: %d episodes, %d entities",
        results["deleted_groups"],
        results["total_episodes"],
        results["total_entities"],
    )
    return results


def _require_confirmation(operation: str, group_id: str | None = None) -> None:
    """Exit with error if confirmation not provided."""
    print("ERROR: Deletion requires --confirm flag")
    if group_id:
        print(f"\nTo delete group '{group_id}', run:")
        print(f"  python -m scripts.memory.cleanup_legacy --delete {group_id} --confirm")
    else:
        print("\nTo delete all legacy groups, run:")
        print("  python -m scripts.memory.cleanup_legacy --delete-all --confirm")
        print("\nWARNING: This will permanently delete all legacy groups!")
    sys.exit(1)


async def main():
    parser = argparse.ArgumentParser(description="Cleanup legacy groups in Graphiti database")
    parser.add_argument("--list", action="store_true", help="List legacy groups")
    parser.add_argument("--review", help="Review episodes in a legacy group")
    parser.add_argument("--delete", help="Delete a specific legacy group")
    parser.add_argument("--delete-all", action="store_true", help="Delete all legacy groups")
    parser.add_argument(
        "--confirm", action="store_true", help="Confirm deletion (required for delete operations)"
    )
    args = parser.parse_args()

    if args.list:
        print_legacy_groups_list(await list_legacy_groups())
    elif args.review:
        await review_group(args.review)
    elif args.delete:
        if not args.confirm:
            _require_confirmation("delete", args.delete)
        result = await delete_group(args.delete, confirm=True)
        if result["success"]:
            print_delete_result(result)
    elif args.delete_all:
        if not args.confirm:
            _require_confirmation("delete-all")
        print_delete_all_result(await delete_all_legacy_groups(confirm=True))
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
