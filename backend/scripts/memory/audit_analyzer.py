"""Episode analysis and statistics for auditing."""

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any


def format_timestamp(timestamp: Any) -> str:
    """Format Neo4j timestamp to ISO string."""
    if hasattr(timestamp, "to_native"):
        return timestamp.to_native().isoformat()
    return str(timestamp)


def is_verbose_content(content: str) -> bool:
    """Check if content contains verbose/conversational patterns."""
    indicators = [
        "you should",
        "i recommend",
        "please",
        "thank you",
        "let me know",
        "feel free",
    ]
    return any(indicator in content.lower() for indicator in indicators)


def is_legacy_group(group_id: str) -> bool:
    """Check if group_id matches legacy patterns."""
    return group_id.startswith(("user-", "test-", "session-")) or group_id in ("default", "none")


def analyze_episodes(
    records: list[dict[str, Any]], verbose: bool = False, include_episodes: bool = False
) -> dict[str, Any]:
    """
    Analyze episode records and build statistics.

    Args:
        records: List of episode records from Neo4j
        verbose: Include verbose pattern detection
        include_episodes: Include episode details in group stats

    Returns:
        Analysis results dict
    """
    group_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "entity_count": 0, "episodes": []}
    )
    verbose_patterns: list[dict[str, Any]] = []
    total_episodes = 0

    for record in records:
        total_episodes += 1
        group_id = record["group_id"] or "none"
        content = record["content"] or ""
        entity_edges = record["entity_edges"] or []

        # Update group stats
        group_stats[group_id]["count"] += 1
        group_stats[group_id]["entity_count"] += len(entity_edges)

        # Verbose pattern detection
        if verbose and is_verbose_content(content):
            verbose_patterns.append(
                {
                    "uuid": record["uuid"][:8],
                    "group_id": group_id,
                    "content_preview": content[:150],
                    "created_at": format_timestamp(record["created_at"]),
                }
            )

        # Episode details for verbose + filtered view
        if include_episodes:
            group_stats[group_id]["episodes"].append(
                {
                    "uuid": record["uuid"][:8],
                    "name": record["name"],
                    "content_length": len(content),
                    "entity_count": len(entity_edges),
                    "created_at": format_timestamp(record["created_at"]),
                }
            )

    # Identify legacy groups
    legacy_groups = {
        group_id: stats for group_id, stats in group_stats.items() if is_legacy_group(group_id)
    }

    return {
        "audit_date": datetime.now(UTC).isoformat(),
        "total_episodes": total_episodes,
        "total_groups": len(group_stats),
        "legacy_groups_count": len(legacy_groups),
        "group_distribution": {group_id: stats["count"] for group_id, stats in group_stats.items()},
        "entity_distribution": {
            group_id: stats["entity_count"] for group_id, stats in group_stats.items()
        },
        "legacy_groups": legacy_groups,
        "verbose_pattern_count": len(verbose_patterns),
        "verbose_patterns": verbose_patterns if verbose else [],
    }
