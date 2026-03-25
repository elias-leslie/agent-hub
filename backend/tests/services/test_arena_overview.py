"""Tests for Arena overview aggregation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_get_arena_overview_honors_requested_window_for_improvement_signals() -> None:
    from app.services.arena_overview import get_arena_overview

    mock_db = AsyncMock()
    persona_id_result = MagicMock()
    persona_id_result.scalar_one_or_none.return_value = None
    mock_db.execute.side_effect = [persona_id_result]

    signal_snapshot = {
        "agent_signal_volume": [],
        "repeated_issues": [],
        "recent_benchmark_experiments": [],
        "open_regression_clusters": [],
        "memory_utilization": {
            "injection_sessions": 0,
            "citation_sessions": 0,
            "lookup_after_injection_sessions": 0,
            "citation_session_rate": 0.0,
            "assistant_citation_rate": 0.0,
            "selected_reference_citation_rate": 0.0,
            "memory_search_calls": 0,
            "memory_get_calls": 0,
            "memory_debug_coverage_rate": 0.0,
        },
        "memory_governance": {
            "active_count": 0,
            "active_agent_count": 0,
            "health_status": "healthy",
            "by_context_kind": {},
            "targeted_count": 0,
            "explicit_exclusion_count": 0,
            "untargeted_reference_count": 0,
            "untargeted_reference_samples": [],
            "policy_with_targeting_count": 0,
            "missing_reference_summary_count": 0,
            "missing_capability_summary_count": 0,
            "oversized_policy_count": 0,
            "oversized_policy_samples": [],
            "alias_trigger_task_type_count": 0,
            "startup_profile_agent_target_count": 0,
            "startup_profile_agent_target_samples": [],
            "invalid_trigger_task_type_count": 0,
            "invalid_trigger_task_type_samples": [],
            "custom_memory_config_agent_count": 0,
            "project_index_disabled_agent_count": 0,
            "tool_capabilities_disabled_agent_count": 0,
            "reference_index_disabled_agent_count": 0,
            "memory_exclusion_agent_count": 0,
            "excluded_memory_uuid_count": 0,
            "hard_issue_count": 0,
            "soft_issue_count": 0,
            "soft_limit_breach_count": 0,
            "issue_count": 0,
        },
        "low_yield_references": [],
    }

    with patch(
        "app.services.arena_overview.collect_improvement_signal_snapshot",
        new=AsyncMock(return_value=signal_snapshot),
    ) as mock_collect:
        overview = await get_arena_overview(
            mock_db,
            active_agents=[],
            days=90,
            project_id="agent-hub",
        )

    assert overview["days"] == 90
    mock_collect.assert_awaited_once_with(
        project_id="agent-hub",
        primary_agent_slug="persona",
        days_back=90,
        include_team=True,
        max_agents=8,
        max_experiments=4,
        max_clusters=6,
        max_reference_items=6,
    )
