"""Tests for memory import change detection helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent_hub_st.memory_batch_import_changes import (
    detect_property_updates,
    fetch_current_episodes,
)


@patch("agent_hub_st.memory_batch_import_changes.agent_hub_request")
def test_fetch_current_episodes_paginates_until_exhausted(mock_request: MagicMock) -> None:
    mock_request.side_effect = [
        {
            "episodes": [{"uuid": "ep-1", "summary": "one"}],
            "has_more": True,
            "cursor": "cursor-1",
        },
        {
            "episodes": [{"uuid": "ep-2", "summary": "two"}],
            "has_more": False,
            "cursor": None,
        },
    ]

    episodes = fetch_current_episodes()

    assert episodes == {
        "ep-1": {"uuid": "ep-1", "summary": "one"},
        "ep-2": {"uuid": "ep-2", "summary": "two"},
    }
    assert mock_request.call_count == 2
    assert mock_request.call_args_list[1].kwargs["params"]["cursor"] == "cursor-1"


def test_detect_property_updates_skips_unchanged_fields() -> None:
    imported = {
        "ep-1": {
            "uuid": "ep-1",
            "summary": "Stable summary",
            "trigger_task_types": ["feature"],
            "pinned": True,
        }
    }
    current = {
        "ep-1": {
            "uuid": "ep-1",
            "summary": "Stable summary",
            "trigger_task_types": ["feature"],
            "pinned": True,
        }
    }

    updates = detect_property_updates(imported, current, content_changes=[])

    assert updates == []


def test_detect_property_updates_uses_category_fallback_and_only_changed_fields() -> None:
    imported = {
        "ep-1": {
            "uuid": "ep-1",
            "category": "guardrail",
            "summary": "Updated summary",
            "trigger_task_types": ["feature", "bug"],
            "pinned": True,
        }
    }
    current = {
        "ep-1": {
            "uuid": "ep-1",
            "injection_tier": "reference",
            "summary": "Old summary",
            "trigger_task_types": ["feature"],
            "pinned": False,
        }
    }

    updates = detect_property_updates(imported, current, content_changes=[])

    assert updates == [
        {
            "uuid": "ep-1",
            "injection_tier": "guardrail",
            "summary": "Updated summary",
            "trigger_task_types": ["feature", "bug"],
            "pinned": True,
        }
    ]
