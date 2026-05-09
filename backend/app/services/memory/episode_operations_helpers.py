"""
Helper utilities for episode_operations.py.

Contains record conversion helpers that work with dict results from MemoryRepository.
"""

from types import SimpleNamespace
from typing import Any


def record_to_get_dict(record: dict[str, Any]) -> dict[str, Any]:
    """Convert a MemoryRepository dict to the episode detail dict used by get/batch-get.

    The input is a dict from MemoryRepository._to_dict() which already has
    the correct keys. This function normalizes defaults for backward compatibility.
    """
    return {
        "uuid": record.get("uuid", ""),
        "name": record.get("name") or "",
        "content": record.get("content", ""),
        "injection_tier": record.get("injection_tier"),
        "source_description": record.get("source_description") or "",
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "version": record.get("version"),
        "pinned": record.get("pinned", False),
        "auto_inject": record.get("auto_inject", False),
        "display_order": record.get("display_order", 50),
        "trigger_task_types": record.get("trigger_task_types") or [],
        "trigger_phases": record.get("trigger_phases") or [],
        "summary": record.get("summary"),
        "render_mode": record.get("render_mode"),
        "context_kind": record.get("context_kind") or "reference",
        "applicability": record.get("applicability") or {},
        "loaded_count": record.get("loaded_count", 0),
        "referenced_count": record.get("referenced_count", 0),
        "helpful_count": record.get("helpful_count", 0),
        "harmful_count": record.get("harmful_count", 0),
        "utility_score": record.get("utility_score"),
        "lifecycle_score": record.get("lifecycle_score"),
    }


def record_to_episode(rec: dict[str, Any]) -> SimpleNamespace:
    """Convert a MemoryRepository dict to an Episode-like object.

    Returns a SimpleNamespace with Episode-like attributes for
    backward compatibility with code that expects attribute access.
    """
    return SimpleNamespace(
        uuid=rec.get("uuid", ""),
        name=rec.get("name"),
        content=rec.get("content", ""),
        source=rec.get("source") or rec.get("memory_type", ""),
        source_description=rec.get("source_description") or "",
        created_at=rec.get("created_at"),
        updated_at=rec.get("updated_at"),
        version=rec.get("version"),
        valid_at=rec.get("valid_at"),
        entity_edges=[],
        injection_tier=rec.get("injection_tier"),
        summary=rec.get("summary"),
        context_kind=rec.get("context_kind") or "reference",
        applicability=rec.get("applicability") or {},
        loaded_count=rec.get("loaded_count", 0),
        referenced_count=rec.get("referenced_count", 0),
        helpful_count=rec.get("helpful_count", 0),
        harmful_count=rec.get("harmful_count", 0),
        utility_score=rec.get("utility_score"),
        pinned=rec.get("pinned", False),
        tags=rec.get("tags") or [],
        trigger_task_types=rec.get("trigger_task_types") or [],
        trigger_phases=rec.get("trigger_phases") or [],
        group_id=rec.get("group_id"),
    )
