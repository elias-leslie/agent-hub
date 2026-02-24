"""
Edge cleanup operations.

In PostgreSQL there are no graph "edges" — this module is a no-op stub
kept for backward compatibility with callers that import cleanup_orphaned_edges.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def cleanup_orphaned_edges(
    driver: Any = None,
    group_id: str = "",
) -> dict[str, Any]:
    """No-op — graph edges do not exist in PostgreSQL.

    Kept for backward compatibility with callers (e.g. service_cleanup.py).

    Returns:
        Dict with zero counts and a note that this is a no-op.
    """
    logger.debug("cleanup_orphaned_edges is a no-op in PostgreSQL mode")
    return {
        "edges_updated": 0,
        "edges_deleted": 0,
        "stale_refs_removed": 0,
        "note": "No-op: graph edges do not exist in PostgreSQL",
    }
