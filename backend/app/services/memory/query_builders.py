"""
Query helpers and field definitions for memory operations.

Previously contained Cypher query builders for Neo4j. Now provides
backward-compatible helper functions. Most callers have migrated to
using MemoryRepository directly.
"""

from typing import Any

# These Cypher field constants are kept for backward compatibility with
# any remaining callers (e.g. episode_operations_helpers.py). They are
# not used in new PostgreSQL code paths.
EPISODE_FIELDS = ""
EPISODE_GET_FIELDS = ""


def build_category_filter(category: str | None) -> str:
    """Build filter string for category. Kept for backward compat."""
    return category or ""


def convert_neo4j_datetime(dt: Any) -> Any:
    """Convert Neo4j DateTime to Python datetime if needed.

    In the PostgreSQL path, datetimes are already Python datetime objects,
    so this is effectively a passthrough. Kept for backward compatibility.
    """
    if dt is not None and hasattr(dt, "to_native"):
        return dt.to_native()
    return dt
