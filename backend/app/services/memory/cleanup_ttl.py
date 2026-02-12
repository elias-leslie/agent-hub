"""
TTL-based memory cleanup operations.

Handles cleanup of memories that haven't been accessed within TTL period.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, cast

from graphiti_core.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)


async def _get_last_activity(driver: Any, group_id: str) -> datetime | None:
    """Get the timestamp of the last episode created in the group."""
    query = """
    MATCH (e:Episodic {group_id: $group_id})
    RETURN max(e.created_at) AS last_activity
    """
    records, _, _ = await driver.execute_query(query, group_id=group_id)

    if not records or not records[0]["last_activity"]:
        return None

    last_activity = records[0]["last_activity"]
    if hasattr(last_activity, "to_native"):
        # cast to Any first to avoid type checking issues with to_native
        return cast(datetime, last_activity.to_native())
    return cast(datetime, last_activity)


async def _delete_stale_edges(
    driver: Any,
    group_id: str,
    cutoff: datetime,
) -> int:
    """Delete edges that haven't been accessed since cutoff date."""
    query = """
    MATCH (e:EntityEdge {group_id: $group_id})
    WHERE e.last_accessed_at IS NOT NULL
      AND e.last_accessed_at < datetime($cutoff)
    WITH e LIMIT 100
    DETACH DELETE e
    RETURN count(e) AS deleted
    """
    records, _, _ = await driver.execute_query(
        query,
        group_id=group_id,
        cutoff=cutoff.isoformat(),
    )
    return records[0]["deleted"] if records else 0


async def cleanup_stale_memories(
    driver: Any,
    group_id: str,
    ttl_days: int = 30,
) -> dict[str, Any]:
    """
    Clean up memories that haven't been accessed within TTL period.

    Implements system activity safeguard: if the system itself hasn't been
    active for 30+ days (no new episodes), cleanup is skipped to prevent
    accidental mass deletion when system resumes.

    Args:
        driver: Neo4j driver instance
        group_id: Group ID to clean up
        ttl_days: Days without access before memory is considered stale

    Returns:
        Dict with cleanup results: deleted count, skipped, and reason
    """
    now = utc_now()

    try:
        last_activity = await _get_last_activity(driver, group_id)

        if not last_activity:
            return {"deleted": 0, "skipped": True, "reason": "No episodes found in group"}

        days_inactive = (now - last_activity).days

        if days_inactive >= ttl_days:
            logger.warning(
                "System inactive for %d days, skipping cleanup to prevent mass deletion",
                days_inactive,
            )
            return {
                "deleted": 0,
                "skipped": True,
                "reason": f"System inactive for {days_inactive} days - cleanup skipped as safeguard",
            }

    except Exception as e:
        logger.error("Failed to check system activity: %s", e)
        return {"deleted": 0, "skipped": True, "reason": f"Activity check failed: {e}"}

    # Find and delete stale edges (not accessed within TTL)
    cutoff = now - timedelta(days=ttl_days)

    try:
        deleted = await _delete_stale_edges(driver, group_id, cutoff)
        logger.info("Cleanup complete for group %s: %d stale memories deleted", group_id, deleted)
        return {"deleted": deleted, "skipped": False, "reason": None}

    except Exception as e:
        logger.error("Cleanup failed: %s", e)
        return {"deleted": 0, "skipped": True, "reason": f"Cleanup query failed: {e}"}
