"""Tests for memory governance snapshot generation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_collect_memory_governance_snapshot_summarizes_routing_quality() -> None:
    from app.services.memory.governance import collect_memory_governance_snapshot

    mock_db = AsyncMock()
    execute_result = MagicMock()
    execute_result.all.return_value = [
        SimpleNamespace(
            id="11111111-1111-1111-1111-111111111111",
            name="Tool doc",
            content="Use st memory search first.",
            summary="tool lookup",
            context_kind="capability",
            memory_type="reference",
            tier=3,
            trigger_task_types=["testing", "security"],
            loaded_count=25,
            applicability={
                "consumer_profiles": ["agent_startup"],
                "exclude_consumer_profiles": [],
                "agent_slugs": [],
                "exclude_agent_slugs": [],
                "audience_tags": ["operator-tooling"],
                "exclude_audience_tags": [],
            },
        ),
        SimpleNamespace(
            id="aaaaaaa1-1111-1111-1111-111111111111",
            name="Dead startup route",
            content="Startup-only tool doc that also targets persona.",
            summary="dead route",
            context_kind="capability",
            memory_type="reference",
            tier=3,
            trigger_task_types=[],
            loaded_count=12,
            applicability={
                "consumer_profiles": ["agent_startup"],
                "exclude_consumer_profiles": [],
                "agent_slugs": ["persona"],
                "exclude_agent_slugs": [],
                "audience_tags": [],
                "exclude_audience_tags": [],
            },
        ),
        SimpleNamespace(
            id="22222222-2222-2222-2222-222222222222",
            name="Bloated rule",
            content="x" * 320,
            summary=None,
            context_kind="policy",
            memory_type="mandate",
            tier=1,
            trigger_task_types=[],
            loaded_count=9,
            applicability={},
        ),
        SimpleNamespace(
            id="33333333-3333-3333-3333-333333333333",
            name="Broad reference",
            content="Reference body",
            summary="",
            context_kind="reference",
            memory_type="reference",
            tier=3,
            trigger_task_types=[],
            loaded_count=18,
            applicability={},
        ),
        SimpleNamespace(
            id="44444444-4444-4444-4444-444444444444",
            name="Archived note",
            content="Old archived reference",
            summary="archived",
            context_kind="reference",
            memory_type="reference",
            tier=4,
            trigger_task_types=["security"],
            loaded_count=99,
            applicability={},
        ),
    ]
    agent_result = MagicMock()
    agent_result.scalars.return_value.all.return_value = [
        SimpleNamespace(
            slug="coder",
            memory_config={
                "tool_capabilities_enabled": False,
                "project_index_enabled": True,
                "reference_index_enabled": True,
                "exclude_memory_uuids": ["deadbeef"],
            },
        ),
        SimpleNamespace(
            slug="note-titler",
            memory_config=None,
        ),
    ]
    mock_db.execute.side_effect = [execute_result, agent_result]

    snapshot = await collect_memory_governance_snapshot(mock_db)

    assert snapshot["active_count"] == 5
    assert snapshot["clean_review_count"] == 0
    assert snapshot["pending_review_count"] == 5
    assert snapshot["needs_action_review_count"] == 0
    assert snapshot["review_coverage_count"] == 0
    assert snapshot["health_status"] == "critical"
    assert snapshot["by_context_kind"] == {
        "capability": 2,
        "policy": 1,
        "reference": 2,
    }
    assert snapshot["targeted_count"] == 2
    assert snapshot["untargeted_reference_count"] == 1
    assert snapshot["untargeted_reference_samples"][0]["label"] == "Broad reference"
    assert snapshot["missing_reference_summary_count"] == 1
    assert snapshot["missing_capability_summary_count"] == 0
    assert snapshot["oversized_policy_count"] == 1
    assert snapshot["oversized_policy_samples"][0]["label"] == "Bloated rule"
    assert snapshot["alias_trigger_task_type_count"] == 1
    assert snapshot["startup_profile_agent_target_count"] == 1
    assert snapshot["startup_profile_agent_target_samples"][0]["label"] == "Dead startup route"
    assert snapshot["invalid_trigger_task_type_count"] == 1
    assert snapshot["invalid_trigger_task_type_samples"][0]["invalid_types"] == ["security"]
    assert snapshot["active_agent_count"] == 2
    assert snapshot["custom_memory_config_agent_count"] == 1
    assert snapshot["tool_capabilities_disabled_agent_count"] == 1
    assert snapshot["memory_exclusion_agent_count"] == 1
    assert snapshot["excluded_memory_uuid_count"] == 1
    assert snapshot["hard_issue_count"] == 8
    assert snapshot["soft_issue_count"] == 2
    assert snapshot["soft_limit_breach_count"] == 0
    assert snapshot["issue_count"] == 10
