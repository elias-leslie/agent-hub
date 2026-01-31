"""
Cypher query builders and field definitions for memory operations.

Centralizes common query patterns and field selections to reduce duplication.
"""

from typing import Any

# Standard episode fields returned by queries
EPISODE_FIELDS = """
    e.uuid AS uuid,
    e.name AS name,
    e.content AS content,
    e.source AS source,
    e.source_description AS source_description,
    e.created_at AS created_at,
    e.valid_at AS valid_at,
    e.entity_edges AS entity_edges,
    e.injection_tier AS injection_tier,
    e.summary AS summary,
    coalesce(e.loaded_count, 0) AS loaded_count,
    coalesce(e.referenced_count, 0) AS referenced_count,
    coalesce(e.helpful_count, 0) AS helpful_count,
    coalesce(e.harmful_count, 0) AS harmful_count,
    e.utility_score AS utility_score,
    coalesce(e.pinned, false) AS pinned
"""

# Episode fields for get_episode (includes injection_tier for compatibility)
EPISODE_GET_FIELDS = """
    e.uuid AS uuid,
    e.name AS name,
    e.content AS content,
    e.injection_tier AS injection_tier,
    e.source_description AS source_description,
    e.created_at AS created_at,
    coalesce(e.pinned, false) AS pinned,
    coalesce(e.auto_inject, false) AS auto_inject,
    coalesce(e.display_order, 50) AS display_order,
    coalesce(e.trigger_task_types, []) AS trigger_task_types,
    e.summary AS summary,
    coalesce(e.loaded_count, 0) AS loaded_count,
    coalesce(e.referenced_count, 0) AS referenced_count,
    coalesce(e.helpful_count, 0) AS helpful_count,
    coalesce(e.harmful_count, 0) AS harmful_count,
    e.utility_score AS utility_score
"""


def build_category_filter(category: str | None) -> str:
    """Build WHERE clause for category filtering."""
    if category:
        return f"AND e.injection_tier = '{category}'"
    return ""


def convert_neo4j_datetime(dt: Any) -> Any:
    """Convert Neo4j DateTime to Python datetime if needed."""
    if dt is not None and hasattr(dt, "to_native"):
        return dt.to_native()
    return dt
