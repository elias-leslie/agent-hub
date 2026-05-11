"""Tests for memory analytics dashboard service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.services.memory.analytics_models import (
    MemoryUtilizationMetrics,
    ScopeDistribution,
    TierDistribution,
    TopMemory,
)
from app.services.memory.analytics_service import (
    _build_outcome_summary,
    get_memory_dashboard,
)
from app.services.memory.st_usage_memory import (
    StUsageCommandMetric,
    StUsageMemory,
    StUsageQuickEntry,
)


def test_build_outcome_summary_tracks_coverage_and_unknowns() -> None:
    """Outcome summary must expose sparse reporting instead of hiding it."""
    summary = _build_outcome_summary(
        [
            {"task_succeeded": True},
            {"task_succeeded": True},
            {"task_succeeded": False},
            {"task_succeeded": None},
        ]
    )

    assert summary.success_count == 2
    assert summary.fail_count == 1
    assert summary.unknown_count == 1
    assert summary.known_count == 3
    assert summary.coverage_rate == 0.75
    assert summary.success_rate == 2 / 3


@pytest.mark.asyncio
async def test_get_memory_dashboard_separates_state_and_activity() -> None:
    """Dashboard keeps current-state and recent-activity data distinct."""
    now = datetime.now(UTC)

    with (
        patch(
            "app.services.memory.analytics_service.get_tier_distribution",
            new_callable=AsyncMock,
            return_value=[TierDistribution(tier="reference", count=3, percentage=100.0)],
        ),
        patch(
            "app.services.memory.analytics_service.get_scope_distribution",
            new_callable=AsyncMock,
            return_value=[ScopeDistribution(scope="global", count=3, percentage=100.0)],
        ),
        patch(
            "app.services.memory.analytics_service.get_usage_aggregates",
            new_callable=AsyncMock,
            return_value={"loaded": 30, "referenced": 10, "helpful": 5, "harmful": 1, "success": 4},
        ),
        patch(
            "app.services.memory.analytics_service.get_avg_utility_score",
            new_callable=AsyncMock,
            return_value=0.5,
        ),
        patch(
            "app.services.memory.analytics_service.get_avg_lifecycle_score",
            new_callable=AsyncMock,
            return_value=0.7,
        ),
        patch(
            "app.services.memory.analytics_service.get_lifecycle_by_tier",
            new_callable=AsyncMock,
            return_value={"reference": 0.7},
        ),
        patch(
            "app.services.memory.analytics_service.get_top_memories_query",
            new_callable=AsyncMock,
            return_value=[
                TopMemory(
                    uuid="abc",
                    content="test",
                    injection_tier="reference",
                    utility_score=0.9,
                    loaded_count=5,
                    referenced_count=4,
                    lifecycle_score=0.8,
                )
            ],
        ),
        patch(
            "app.services.memory.analytics_service.get_recent_usage_totals",
            new_callable=AsyncMock,
            return_value={"loaded": 6, "cited": 3, "helpful": 3, "harmful": 0, "success": 1},
        ),
        patch(
            "app.services.memory.analytics_service.get_injection_metrics_summary",
            new_callable=AsyncMock,
            return_value={
                "total_injections": 4,
                "period_start": now.isoformat(),
                "period_end": now.isoformat(),
                "period_granularity": "hour",
                "by_variant": [],
                "by_period": [],
                "overall_success_rate": 0.5,
                "overall_citation_rate": 0.25,
                "outcomes": _build_outcome_summary([{"task_succeeded": True}, {"task_succeeded": None}]),
            },
        ),
        patch(
            "app.services.memory.analytics_service.get_tier_changes_summary",
            new_callable=AsyncMock,
            return_value={"by_type": {}, "recent": [], "total": 0},
        ),
        patch(
            "app.services.memory.analytics_service.get_memory_utilization_summary",
            new_callable=AsyncMock,
            return_value=MemoryUtilizationMetrics(
                injection_sessions=4,
                citation_sessions=2,
                lookup_sessions=3,
                lookup_after_injection_sessions=2,
                memory_search_calls=3,
                memory_get_calls=2,
                assistant_message_count=5,
                assistant_messages_with_memory_citations=2,
                citation_session_rate=0.5,
                lookup_session_rate=0.75,
                expansion_session_rate=0.5,
                assistant_citation_rate=0.4,
                sessions_with_selected_references=2,
                sessions_with_cited_selected_references=1,
                selected_reference_count=6,
                selected_reference_cited_count=3,
                selected_reference_citation_rate=0.5,
                selected_reference_session_rate=0.5,
                memory_inject_event_count=4,
                memory_inject_events_with_debug=4,
                memory_debug_coverage_rate=1.0,
            ),
        ),
        patch(
            "app.services.memory.analytics_service.get_recent_st_usage_memory",
            new_callable=AsyncMock,
            return_value=StUsageMemory(
                quick=["st pulse --gate | preflight; edit only if clear"],
                observed=5,
                help_count=1,
                generated_at=now,
                quick_entries=[
                    StUsageQuickEntry(
                        command="st pulse --gate",
                        description="preflight; edit only if clear",
                        source="learned",
                    )
                ],
                command_metrics=[
                    StUsageCommandMetric(
                        command_key="pulse",
                        uses=4,
                        help_lookups=1,
                        injected_example="st pulse --gate | preflight; edit only if clear",
                        last_seen=now.isoformat(),
                    )
                ],
            ),
        ),
    ):
        dashboard = await get_memory_dashboard(
            lookback_delta=timedelta(hours=1),
            lookback_label="1h",
            top_memories_sort_by="utility_score",
        )

    assert dashboard.state.total_episodes == 3
    assert dashboard.state.usage_totals.loaded == 30
    assert dashboard.activity.lookback == "1h"
    assert dashboard.activity.usage_totals.loaded == 6
    assert dashboard.activity.injection_metrics.period_granularity == "hour"
    assert dashboard.activity.injection_metrics.outcomes.unknown_count == 1
    assert dashboard.activity.utilization.lookup_after_injection_sessions == 2
    assert dashboard.activity.utilization.selected_reference_citation_rate == 0.5
    assert dashboard.activity.st_usage.observed_commands == 5
    assert dashboard.activity.st_usage.help_rate == 0.2
    assert dashboard.activity.st_usage.quick_entries[0].command == "st pulse --gate"
    # quick_entries here are still set by the test fixture; telemetry-only
    # builders now emit [] but the dashboard surface still supports them
    # when an analytics caller provides them directly.
