"""TTL-based memory cleanup — graduated retirement (no hard deletes).

Replaces the old hard-delete approach with graduated retirement:
memories are tombstoned (content cleared, status='retired') rather
than permanently destroyed.
"""

import logging
from typing import Any

from .retirement import retire_stale_archives

logger = logging.getLogger(__name__)


async def cleanup_stale_memories() -> dict[str, Any]:
    """Clean up stale memories via graduated retirement.

    Retirement is global and uses its own threshold (``retirement.RETIREMENT_DAYS``).

    Returns:
        Dict with cleanup results: retired count, skipped, and reason.
    """
    try:
        result = await retire_stale_archives()
        retired = result.get("retired", 0)
        if retired:
            logger.info("Retirement cleanup: %d memories tombstoned", retired)
        return {
            "deleted": 0,  # no more hard deletes
            "retired": retired,
            "skipped": result.get("skipped", False),
            "reason": result.get("reason", ""),
        }

    except Exception as e:
        logger.error("Cleanup failed: %s", e)
        return {"deleted": 0, "retired": 0, "skipped": True, "reason": f"Cleanup failed: {e}"}
