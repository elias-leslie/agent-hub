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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


LEGACY_GROUP_PREFIXES = ["user-", "test-", "session-", "task-"]
LEGACY_GROUP_NAMES = ["default", "none"]


def is_legacy_group(group_id: str) -> bool:
    """Check if a group_id is a legacy group."""
    if group_id in LEGACY_GROUP_NAMES:
        return True
    return any(group_id.startswith(prefix) for prefix in LEGACY_GROUP_PREFIXES)


async def list_legacy_groups() -> list[dict]:
    """
    List all legacy groups with episode and entity counts.

    Returns:
        List of legacy group dicts
    """
    graphiti = get_graphiti()
    driver = graphiti.driver

    # Get episode counts by group
    episode_query = """
    MATCH (e:Episodic)
    RETURN e.group_id AS group_id, count(e) AS count
    ORDER BY count DESC
    """
    episode_records, _, _ = await driver.execute_query(episode_query)

    # Get entity counts by group
    entity_query = """
    MATCH (e:Entity)
    RETURN e.group_id AS group_id, count(e) AS count
    ORDER BY count DESC
    """
    entity_records, _, _ = await driver.execute_query(entity_query)

    # Combine into a dict
    group_stats: dict[str, dict] = {}
    for record in episode_records:
        group_id = record["group_id"] or "none"
        if is_legacy_group(group_id):
            group_stats[group_id] = {"episode_count": record["count"], "entity_count": 0}

    for record in entity_records:
        group_id = record["group_id"] or "none"
        if is_legacy_group(group_id):
            if group_id not in group_stats:
                group_stats[group_id] = {"episode_count": 0, "entity_count": 0}
            group_stats[group_id]["entity_count"] = record["count"]

    # Convert to list
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
    """
    Review episodes in a legacy group.

    Args:
        group_id: Group ID to review
    """
    graphiti = get_graphiti()
    driver = graphiti.driver

    query = """
    MATCH (e:Episodic {group_id: $group_id})
    RETURN e.uuid AS uuid, e.name AS name, e.content AS content,
           e.created_at AS created_at, e.source_description AS source_description
    ORDER BY e.created_at DESC
    LIMIT 50
    """
    records, _, _ = await driver.execute_query(query, group_id=group_id)

    print(f"\nReviewing group: {group_id}")
    print("=" * 60)
    print(f"Total episodes: {len(records)} (showing first 50)")
    print()

    for i, record in enumerate(records, 1):
        created_at = record["created_at"]
        if hasattr(created_at, "to_native"):
            created_at = created_at.to_native().isoformat()[:10]

        print(f"{i}. [{record['uuid'][:8]}] {record['name']}")
        print(f"   Created: {created_at}")
        print(f"   Source: {record['source_description']}")
        print(f"   Content: {record['content'][:150]}...")
        print()

    await graphiti.close()


async def delete_group(group_id: str, confirm: bool = False) -> dict:
    """
    Delete all episodes and entities in a legacy group.

    Args:
        group_id: Group ID to delete
        confirm: Whether deletion is confirmed

    Returns:
        Dict with deletion stats
    """
    if not confirm:
        logger.error("Deletion must be confirmed with --confirm flag")
        return {"deleted_episodes": 0, "deleted_entities": 0, "success": False}

    graphiti = get_graphiti()
    driver = graphiti.driver

    logger.warning("Deleting group: %s", group_id)

    # Delete episodes
    episode_query = """
    MATCH (e:Episodic {group_id: $group_id})
    WITH e
    DETACH DELETE e
    RETURN count(e) AS deleted
    """
    ep_records, _, _ = await driver.execute_query(episode_query, group_id=group_id)
    deleted_episodes = ep_records[0]["deleted"] if ep_records else 0

    # Delete entities
    entity_query = """
    MATCH (e:Entity {group_id: $group_id})
    WITH e
    DETACH DELETE e
    RETURN count(e) AS deleted
    """
    ent_records, _, _ = await driver.execute_query(entity_query, group_id=group_id)
    deleted_entities = ent_records[0]["deleted"] if ent_records else 0

    # Delete edges
    edge_query = """
    MATCH (e:EntityEdge {group_id: $group_id})
    WITH e
    DETACH DELETE e
    RETURN count(e) AS deleted
    """
    edge_records, _, _ = await driver.execute_query(edge_query, group_id=group_id)
    deleted_edges = edge_records[0]["deleted"] if edge_records else 0

    logger.info(
        "Deleted group %s: %d episodes, %d entities, %d edges",
        group_id,
        deleted_episodes,
        deleted_entities,
        deleted_edges,
    )

    await graphiti.close()

    return {
        "group_id": group_id,
        "deleted_episodes": deleted_episodes,
        "deleted_entities": deleted_entities,
        "deleted_edges": deleted_edges,
        "success": True,
    }


async def delete_all_legacy_groups(confirm: bool = False) -> dict:
    """
    Delete all legacy groups.

    Args:
        confirm: Whether deletion is confirmed

    Returns:
        Dict with deletion stats
    """
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
        group_id = group["group_id"]
        result = await delete_group(group_id, confirm=True)

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


async def main():
    parser = argparse.ArgumentParser(description="Cleanup legacy groups in Graphiti database")
    parser.add_argument("--list", action="store_true", help="List legacy groups")
    parser.add_argument("--review", help="Review episodes in a legacy group")
    parser.add_argument("--delete", help="Delete a specific legacy group")
    parser.add_argument(
        "--delete-all",
        action="store_true",
        help="Delete all legacy groups",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm deletion (required for delete operations)",
    )

    args = parser.parse_args()

    if args.list:
        legacy_groups = await list_legacy_groups()

        print("\nLegacy Groups:")
        print("=" * 60)
        if not legacy_groups:
            print("No legacy groups found")
        else:
            total_episodes = sum(g["episode_count"] for g in legacy_groups)
            total_entities = sum(g["entity_count"] for g in legacy_groups)
            print(
                f"Total: {len(legacy_groups)} groups, {total_entities} entities, {total_episodes} episodes"
            )
            print()

            for group in legacy_groups:
                print(
                    f"  {group['group_id']}: {group['entity_count']} entities, {group['episode_count']} episodes"
                )

        print()

    elif args.review:
        await review_group(args.review)

    elif args.delete:
        if not args.confirm:
            print("ERROR: Deletion requires --confirm flag")
            print(f"\nTo delete group '{args.delete}', run:")
            print(f"  python -m scripts.memory.cleanup_legacy --delete {args.delete} --confirm")
            sys.exit(1)

        result = await delete_group(args.delete, confirm=True)
        if result["success"]:
            print(f"\nDeleted group: {result['group_id']}")
            print(f"  Episodes: {result['deleted_episodes']}")
            print(f"  Entities: {result['deleted_entities']}")
            print(f"  Edges: {result['deleted_edges']}")

    elif args.delete_all:
        if not args.confirm:
            print("ERROR: Deletion requires --confirm flag")
            print("\nTo delete all legacy groups, run:")
            print("  python -m scripts.memory.cleanup_legacy --delete-all --confirm")
            print("\nWARNING: This will permanently delete all legacy groups!")
            sys.exit(1)

        result = await delete_all_legacy_groups(confirm=True)
        print(f"\nDeleted {result['deleted_groups']} legacy groups")
        print(f"  Total episodes: {result['total_episodes']}")
        print(f"  Total entities: {result['total_entities']}")

    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
