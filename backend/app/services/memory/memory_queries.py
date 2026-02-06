"""
Neo4j query operations for memory service.

Handles direct database queries for episode validation, access tracking,
batch operations, and cleanup tasks.

This module provides a unified interface by re-exporting functions from
specialized submodules for better organization and maintainability.
"""

# Re-export cleanup operations
from .cleanup_operations import (
    cleanup_orphaned_edges,
    cleanup_orphaned_entities,
    cleanup_stale_memories,
    consolidate_duplicate_entities,
)

# Re-export episode operations
from .episode_operations import (
    batch_get_episodes,
    fetch_episodes_filtered,
    get_episode,
    text_search_episodes,
)

# Re-export tracking operations
from .tracking_operations import (
    update_access_time,
    update_episode_access_time,
    validate_episodes,
    validate_episodes_with_content,
)

__all__ = [
    "batch_get_episodes",
    "cleanup_orphaned_edges",
    "cleanup_orphaned_entities",
    "cleanup_stale_memories",
    "consolidate_duplicate_entities",
    "fetch_episodes_filtered",
    "get_episode",
    "text_search_episodes",
    "update_access_time",
    "update_episode_access_time",
    "validate_episodes",
    "validate_episodes_with_content",
]
