"""Tests for memory episode detail normalization helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.memory.episode_operations_helpers import record_to_get_dict


def test_record_to_get_dict_normalizes_nullable_fields() -> None:
    """Legacy rows with nullable fields should still serialize for detail endpoints."""
    now = datetime.now(UTC)

    result = record_to_get_dict(
        {
            "uuid": "1234",
            "name": None,
            "content": "content",
            "source_description": None,
            "created_at": now,
            "trigger_task_types": None,
            "loaded_count": 1,
            "referenced_count": 2,
            "helpful_count": 3,
            "harmful_count": 4,
            "utility_score": 0.5,
            "lifecycle_score": 0.8,
        }
    )

    assert result["name"] == ""
    assert result["source_description"] == ""
    assert result["trigger_task_types"] == []
    assert result["lifecycle_score"] == 0.8

