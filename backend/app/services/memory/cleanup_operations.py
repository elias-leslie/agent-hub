"""
Memory cleanup operations.

Handles stale memory TTL enforcement and orphaned cleanup.
In PostgreSQL, there are no separate graph edges/entities to clean up,
so edge/entity operations are no-ops that return compatible result dicts.

This module re-exports all cleanup functions for backward compatibility.
"""

from .cleanup_edges import cleanup_orphaned_edges
from .cleanup_entities import (
    cleanup_orphaned_entities,
    consolidate_duplicate_entities,
)
from .cleanup_ttl import cleanup_stale_memories

__all__ = [
    "cleanup_orphaned_edges",
    "cleanup_orphaned_entities",
    "cleanup_stale_memories",
    "consolidate_duplicate_entities",
]
