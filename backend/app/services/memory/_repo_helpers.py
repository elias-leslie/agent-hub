"""Shared helpers and constants for memory repository sub-modules."""

from __future__ import annotations

import uuid as _uuid
from typing import Any

from app.models.memory_unified import Memory

# Tier name <-> numeric tier mapping
TIER_MAP: dict[str, int] = {"mandate": 1, "guardrail": 2, "reference": 3, "archive": 4}
TIER_REVERSE: dict[int, str] = {v: k for k, v in TIER_MAP.items()}


def to_uuid(value: _uuid.UUID | str) -> _uuid.UUID:
    """Coerce a UUID or string to a UUID object."""
    return _uuid.UUID(str(value)) if isinstance(value, str) else value


def to_uuids(values: list[_uuid.UUID | str]) -> list[_uuid.UUID]:
    """Coerce a list of UUID-or-string values to UUID objects."""
    return [to_uuid(v) for v in values]


def to_dict(mem: Memory) -> dict[str, Any]:
    """Convert Memory ORM object to dict (backward compat)."""
    metadata = getattr(mem, "metadata_", None) or {}
    return {
        "uuid": str(mem.id),
        "version": mem.version,
        "content": mem.content,
        "compact_content": metadata.get("compact_content"),
        "content_fingerprint": getattr(mem, "content_fingerprint", None),
        "name": mem.name,
        "summary": mem.summary,
        "memory_type": mem.memory_type,
        "scope": mem.scope,
        "scope_id": mem.scope_id,
        "group_id": mem.group_id,
        "source": mem.source,
        "source_description": mem.source_description,
        "tags": mem.tags or [],
        "context_kind": mem.context_kind,
        "applicability": mem.applicability or {},
        "injection_tier": mem.injection_tier,
        "tier": mem.tier,
        "pinned": mem.pinned,
        "auto_inject": mem.auto_inject,
        "display_order": mem.display_order,
        "trigger_task_types": mem.trigger_task_types or [],
        "trigger_phases": mem.trigger_phases or [],
        "loaded_count": mem.loaded_count,
        "referenced_count": mem.referenced_count,
        "helpful_count": mem.helpful_count,
        "harmful_count": mem.harmful_count,
        "utility_score": mem.utility_score,
        "status": mem.status,
        "review_status": getattr(mem, "review_status", "pending"),
        "sensitivity_tier": getattr(mem, "sensitivity_tier", "normal"),
        "token_count": mem.token_count,
        "lifecycle_score": mem.lifecycle_score,
        "lifecycle_score_updated_at": mem.lifecycle_score_updated_at,
        "retired_at": mem.retired_at,
        "superseded_by": str(mem.superseded_by) if mem.superseded_by else None,
        "metadata": metadata,
        "valid_at": mem.valid_at,
        "created_at": mem.created_at,
        "updated_at": mem.updated_at,
        "last_accessed_at": mem.last_accessed_at,
        "last_reviewed_at": getattr(mem, "last_reviewed_at", None),
    }
