"""
Memory cleanup operations.

Handles orphaned edge cleanup and stale memory TTL enforcement.

This module re-exports all cleanup functions from specialized submodules
for backward compatibility while keeping the codebase well-organized.
"""

# Re-export edge cleanup operations
from .cleanup_edges import cleanup_orphaned_edges

# Re-export entity cleanup operations
from .cleanup_entities import (
    cleanup_orphaned_entities,
    consolidate_duplicate_entities,
)

# Re-export TTL cleanup operations
from .cleanup_ttl import cleanup_stale_memories

__all__ = [
    "cleanup_orphaned_edges",
    "cleanup_orphaned_entities",
    "cleanup_stale_memories",
    "consolidate_duplicate_entities",
]
