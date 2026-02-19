"""
Helper utilities for episode_operations.py.

Contains record conversion helpers and query-building utilities.
"""

from types import SimpleNamespace
from typing import Any

from .query_builders import convert_neo4j_datetime


def record_to_get_dict(record: Any) -> dict[str, Any]:
    """Convert a Neo4j record to the episode detail dict used by get/batch-get."""
    return {
        "uuid": record["uuid"],
        "name": record["name"],
        "content": record["content"],
        "injection_tier": record["injection_tier"],
        "source_description": record["source_description"],
        "created_at": convert_neo4j_datetime(record["created_at"]),
        "pinned": record["pinned"],
        "auto_inject": record["auto_inject"],
        "display_order": record["display_order"],
        "trigger_task_types": record["trigger_task_types"],
        "summary": record["summary"],
        "loaded_count": record["loaded_count"],
        "referenced_count": record["referenced_count"],
        "helpful_count": record["helpful_count"],
        "harmful_count": record["harmful_count"],
        "utility_score": record["utility_score"],
    }


def record_to_episode(rec: dict[str, Any]) -> SimpleNamespace:
    """Convert Neo4j record to Episode-like object."""
    return SimpleNamespace(
        uuid=rec["uuid"],
        name=rec["name"],
        content=rec["content"],
        source=rec["source"],
        source_description=rec["source_description"] or "",
        created_at=convert_neo4j_datetime(rec["created_at"]),
        valid_at=convert_neo4j_datetime(rec["valid_at"]),
        entity_edges=rec["entity_edges"] or [],
        injection_tier=rec["injection_tier"],
        summary=rec["summary"],
        loaded_count=rec["loaded_count"],
        referenced_count=rec["referenced_count"],
        helpful_count=rec["helpful_count"],
        harmful_count=rec["harmful_count"],
        utility_score=rec["utility_score"],
        pinned=rec["pinned"],
        tags=rec.get("tags") or [],
        group_id=rec.get("group_id"),
    )
