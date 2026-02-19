"""
Helper functions for the entity inventory script.
"""

from collections import defaultdict
from datetime import UTC, datetime


def analyze_entity_records(entity_records: list, show_duplicates: bool) -> tuple[dict, dict, int]:
    """
    Analyze entity records from the database.

    Args:
        entity_records: List of records from the entity query
        show_duplicates: Whether to include full entity details in duplicate info

    Returns:
        Tuple of (entity_by_name, group_stats, total_entities)
    """
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

    return entity_by_name, group_stats, total_entities


def find_duplicates(entity_by_name: dict, show_duplicates: bool) -> tuple[dict, int]:
    """
    Identify duplicate entities and calculate deduplication savings.

    Args:
        entity_by_name: Dict mapping entity names to lists of entity dicts
        show_duplicates: Whether to include full entity details in results

    Returns:
        Tuple of (duplicates dict, dedup_savings count)
    """
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

    dedup_savings = sum(info["count"] - 1 for info in duplicates.values())
    return duplicates, dedup_savings


def build_inventory_report(
    total_entities: int,
    entity_by_name: dict,
    total_edges: int,
    duplicates: dict,
    dedup_savings: int,
    group_stats: dict,
    show_duplicates: bool,
) -> dict:
    """
    Build the final inventory report dictionary.

    Args:
        total_entities: Total number of entities
        entity_by_name: Dict mapping entity names to entity lists
        total_edges: Total number of edges
        duplicates: Dict of duplicate entities
        dedup_savings: Number of entities that could be merged
        group_stats: Dict mapping group_id to entity counts
        show_duplicates: Whether to include full duplicate details

    Returns:
        Inventory report dict
    """
    report = {
        "inventory_date": datetime.now(UTC).isoformat(),
        "total_entities": total_entities,
        "unique_entity_names": len(entity_by_name),
        "total_edges": total_edges,
        "duplicate_names": len(duplicates),
        "deduplication_savings": dedup_savings,
        "entity_distribution_by_group": dict(group_stats),
        "top_duplicates": {},
    }

    top_dupes = sorted(duplicates.items(), key=lambda x: x[1]["count"], reverse=True)[:20]
    for name, info in top_dupes:
        report["top_duplicates"][name] = {
            "count": info["count"],
            "groups": dict(info["group_distribution"]),
        }

    if show_duplicates:
        report["all_duplicates"] = duplicates

    return report


def display_report(inventory_report: dict) -> None:
    """
    Print the inventory report to stdout.

    Args:
        inventory_report: The inventory report dict to display
    """
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
        print("\nTop Duplicates (showing up to 20):")
        for name, info in list(inventory_report["top_duplicates"].items()):
            print(f"\n  {name}: {info['count']} instances")
            print(f"    Groups: {dict(info['groups'])}")
