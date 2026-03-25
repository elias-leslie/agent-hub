"""Tests for combined improvement-signal reporting."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql


@pytest.mark.asyncio
async def test_collect_improvement_signal_snapshot_returns_structured_evidence() -> None:
    from app.services.improvement_signals import collect_improvement_signal_snapshot

    now = datetime(2026, 3, 22, 9, 30, tzinfo=UTC)
    performance_logs = [
        SimpleNamespace(
            agent_slug="persona",
            feedback_type="friction",
            content="missed rebuild.sh before verification",
            created_at=now,
            logged_by="system",
        ),
        SimpleNamespace(
            agent_slug="jenny",
            feedback_type="improvement",
            content="tightened heartbeat guidance",
            created_at=now,
            logged_by="persona",
        ),
    ]
    experiments = [
        SimpleNamespace(
            experiment_key="exp-1",
            suite_id="persona-suite-self-correction",
            updated_at=now,
        ),
    ]
    clusters = [
        SimpleNamespace(
            case_id="rebuild_rule_reconsideration",
            occurrence_count=3,
            failure_detail="forgot rebuild.sh",
            last_seen_at=now,
        ),
        SimpleNamespace(
            case_id="session_patience_recent_progress",
            occurrence_count=8,
            failure_detail="All connection attempts failed",
            last_seen_at=now,
        ),
    ]
    memory_events = [
        ("memory_inject", {"reference_selected_uuids": ["ref-1", "ref-2"]}),
        ("memory_inject", {"reference_selected_uuids": ["ref-2"]}),
        ("memory_cite", {"uuids": ["ref-1"]}),
    ]

    mock_db = AsyncMock()
    perf_result = MagicMock()
    perf_result.scalars.return_value.all.return_value = performance_logs
    experiment_result = MagicMock()
    experiment_result.all.return_value = [
        (experiments[0], now),
    ]
    cluster_result = MagicMock()
    cluster_result.scalars.return_value.all.return_value = clusters
    event_result = MagicMock()
    event_result.all.return_value = memory_events
    mock_db.execute.side_effect = [
        perf_result,
        experiment_result,
        cluster_result,
        event_result,
    ]

    @asynccontextmanager
    async def _session():
        yield mock_db

    memory_utilization = SimpleNamespace(
        injection_sessions=4,
        citation_sessions=2,
        lookup_sessions=3,
        lookup_after_injection_sessions=2,
        memory_search_calls=5,
        memory_get_calls=1,
        assistant_message_count=8,
        assistant_messages_with_memory_citations=4,
        citation_session_rate=0.5,
        lookup_session_rate=0.5,
        expansion_session_rate=0.5,
        assistant_citation_rate=0.5,
        sessions_with_selected_references=2,
        sessions_with_cited_selected_references=1,
        selected_reference_count=3,
        selected_reference_cited_count=1,
        selected_reference_citation_rate=0.333,
        selected_reference_session_rate=0.5,
        memory_inject_event_count=2,
        memory_inject_events_with_debug=2,
        memory_debug_coverage_rate=1.0,
    )

    with (
        patch("app.services.improvement_signals.async_session", return_value=_session()),
        patch(
            "app.services.improvement_signals.get_memory_utilization_summary",
            new=AsyncMock(return_value=memory_utilization),
        ),
        patch(
            "app.services.improvement_signals.collect_memory_governance_snapshot",
            new=AsyncMock(
                return_value={
                    "active_count": 12,
                    "active_agent_count": 4,
                    "health_status": "warn",
                    "by_context_kind": {"policy": 4, "reference": 8},
                    "targeted_count": 3,
                    "explicit_exclusion_count": 1,
                    "untargeted_reference_count": 5,
                    "untargeted_reference_samples": [
                        {
                            "uuid": "broad-ref",
                            "label": "broad-ref",
                            "details": "reference · loaded 42",
                            "load_count": 42,
                            "invalid_types": [],
                        }
                    ],
                    "policy_with_targeting_count": 0,
                    "missing_reference_summary_count": 1,
                    "missing_capability_summary_count": 0,
                    "oversized_policy_count": 0,
                    "oversized_policy_samples": [],
                    "alias_trigger_task_type_count": 1,
                    "startup_profile_agent_target_count": 0,
                    "startup_profile_agent_target_samples": [],
                    "invalid_trigger_task_type_count": 0,
                    "invalid_trigger_task_type_samples": [],
                    "custom_memory_config_agent_count": 2,
                    "project_index_disabled_agent_count": 1,
                    "tool_capabilities_disabled_agent_count": 0,
                    "reference_index_disabled_agent_count": 1,
                    "memory_exclusion_agent_count": 0,
                    "excluded_memory_uuid_count": 0,
                    "hard_issue_count": 1,
                    "soft_issue_count": 5,
                    "soft_limit_breach_count": 0,
                    "issue_count": 6,
                }
            ),
        ),
        patch(
            "app.services.improvement_signals.batch_get_episodes",
            new=AsyncMock(
                return_value={
                    "ref-1": {"uuid": "ref-1", "name": "useful-ref", "tags": ["persona-relevant"]},
                    "ref-2": {"uuid": "ref-2", "name": "noisy-ref", "tags": ["debugger-relevant"]},
                }
            ),
        ),
        patch(
            "app.services.improvement_signals.get_benchmark_experiment_summary_by_key",
            new=AsyncMock(
                return_value={
                    "decision": "hold",
                    "decision_reason": "underpowered",
                    "score_delta": {"mean_delta": -0.5},
                    "pass_rate_delta": {"mean_delta": 0.0},
                }
            ),
        ),
    ):
        snapshot = await collect_improvement_signal_snapshot(
            project_id="agent-hub",
            primary_agent_slug="persona",
            days_back=7,
        )

    assert snapshot["agent_signal_volume"][0]["agent_slug"] == "persona"
    assert snapshot["agent_signal_volume"][0]["improvement"] == 1
    assert snapshot["repeated_issues"][0]["feedback_type"] == "friction"
    assert snapshot["repeated_issues"][0]["content"] == "missed rebuild.sh before verification"
    assert snapshot["recent_benchmark_experiments"][0]["suite_id"] == "persona-suite-self-correction"
    assert snapshot["open_regression_clusters"][0]["case_id"] == "rebuild_rule_reconsideration"
    assert len(snapshot["open_regression_clusters"]) == 1
    assert snapshot["memory_utilization"]["selected_reference_citation_rate"] == 0.333
    assert snapshot["memory_governance"]["active_count"] == 12
    assert snapshot["low_yield_references"][0]["label"] == "noisy-ref"


@pytest.mark.asyncio
async def test_build_improvement_signal_digest_combines_evidence_sources() -> None:
    from app.services.improvement_signals import build_improvement_signal_digest

    now = datetime(2026, 3, 22, 9, 30, tzinfo=UTC)
    performance_logs = [
        SimpleNamespace(
            agent_slug="persona",
            feedback_type="friction",
            content="missed rebuild.sh before verification",
            created_at=now,
            logged_by="system",
        ),
        SimpleNamespace(
            agent_slug="persona",
            feedback_type="friction",
            content="missed rebuild.sh before verification",
            created_at=now,
            logged_by="system",
        ),
        SimpleNamespace(
            agent_slug="debugger",
            feedback_type="friction",
            content="ignored st memory search before guessing",
            created_at=now,
            logged_by="persona",
        ),
        SimpleNamespace(
            agent_slug="debugger",
            feedback_type="praise",
            content="good routing cleanup",
            created_at=now,
            logged_by="persona",
        ),
    ]
    experiments = [
        SimpleNamespace(
            experiment_key="exp-1",
            suite_id="persona-suite-self-correction",
            updated_at=now,
        ),
    ]
    clusters = [
        SimpleNamespace(
            case_id="rebuild_rule_reconsideration",
            occurrence_count=3,
            failure_detail="forgot rebuild.sh",
            last_seen_at=now,
        ),
    ]
    memory_events = [
        (
            "memory_inject",
            {"reference_selected_uuids": ["ref-1", "ref-2"]},
        ),
        (
            "memory_inject",
            {"reference_selected_uuids": ["ref-2"]},
        ),
        (
            "memory_cite",
            {"uuids": ["ref-1"]},
        ),
    ]

    mock_db = AsyncMock()
    perf_result = MagicMock()
    perf_result.scalars.return_value.all.return_value = performance_logs
    experiment_result = MagicMock()
    experiment_result.all.return_value = [
        (experiments[0], now),
    ]
    cluster_result = MagicMock()
    cluster_result.scalars.return_value.all.return_value = clusters
    event_result = MagicMock()
    event_result.all.return_value = memory_events
    mock_db.execute.side_effect = [
        perf_result,
        experiment_result,
        cluster_result,
        event_result,
    ]

    @asynccontextmanager
    async def _session():
        yield mock_db

    memory_utilization = SimpleNamespace(
        injection_sessions=4,
        citation_sessions=2,
        lookup_sessions=3,
        lookup_after_injection_sessions=2,
        memory_search_calls=5,
        memory_get_calls=1,
        assistant_message_count=8,
        assistant_messages_with_memory_citations=4,
        citation_session_rate=0.5,
        lookup_session_rate=0.5,
        expansion_session_rate=0.5,
        assistant_citation_rate=0.5,
        sessions_with_selected_references=2,
        sessions_with_cited_selected_references=1,
        selected_reference_count=3,
        selected_reference_cited_count=1,
        selected_reference_citation_rate=0.333,
        selected_reference_session_rate=0.5,
        memory_inject_event_count=2,
        memory_inject_events_with_debug=2,
        memory_debug_coverage_rate=1.0,
    )

    with (
        patch("app.services.improvement_signals.async_session", return_value=_session()),
        patch(
            "app.services.improvement_signals.get_memory_utilization_summary",
            new=AsyncMock(return_value=memory_utilization),
        ),
        patch(
            "app.services.improvement_signals.collect_memory_governance_snapshot",
            new=AsyncMock(
                return_value={
                    "active_count": 12,
                    "active_agent_count": 2,
                    "health_status": "warn",
                    "by_context_kind": {"policy": 4, "reference": 8},
                    "targeted_count": 3,
                    "explicit_exclusion_count": 1,
                    "untargeted_reference_count": 5,
                    "untargeted_reference_samples": [
                        {
                            "uuid": "broad-ref-1",
                            "label": "broad-ref",
                            "details": "reference · loaded 4",
                            "load_count": 4,
                        }
                    ],
                    "policy_with_targeting_count": 0,
                    "missing_reference_summary_count": 1,
                    "missing_capability_summary_count": 0,
                    "oversized_policy_count": 0,
                    "oversized_policy_samples": [],
                    "alias_trigger_task_type_count": 1,
                    "startup_profile_agent_target_count": 0,
                    "startup_profile_agent_target_samples": [],
                    "invalid_trigger_task_type_count": 0,
                    "invalid_trigger_task_type_samples": [],
                    "custom_memory_config_agent_count": 1,
                    "project_index_disabled_agent_count": 0,
                    "tool_capabilities_disabled_agent_count": 1,
                    "reference_index_disabled_agent_count": 0,
                    "memory_exclusion_agent_count": 1,
                    "excluded_memory_uuid_count": 2,
                    "hard_issue_count": 0,
                    "soft_issue_count": 1,
                    "soft_limit_breach_count": 1,
                    "issue_count": 1,
                }
            ),
        ),
        patch(
            "app.services.improvement_signals.batch_get_episodes",
            new=AsyncMock(
                return_value={
                    "ref-1": {
                        "uuid": "ref-1",
                        "name": "useful-ref",
                        "content": "Useful memory",
                        "tags": ["persona-relevant"],
                    },
                    "ref-2": {
                        "uuid": "ref-2",
                        "name": "noisy-ref",
                        "content": "Noisy memory",
                        "tags": ["debugger-relevant"],
                    },
                }
            ),
        ),
        patch(
            "app.services.improvement_signals.get_benchmark_experiment_summary_by_key",
            new=AsyncMock(
                return_value={
                    "decision": "hold",
                    "decision_reason": "underpowered",
                    "score_delta": {"mean_delta": -0.5},
                    "pass_rate_delta": {"mean_delta": 0.0},
                }
            ),
        ),
    ):
        digest = await build_improvement_signal_digest(
            project_id="agent-hub",
            primary_agent_slug="persona",
            days_back=7,
        )

    assert "persona: friction=2" in digest
    assert "debugger: friction=1" in digest
    assert "missed rebuild.sh before verification" in digest
    assert "suite=persona-suite-self-correction decision=hold" in digest
    assert "rebuild_rule_reconsideration [3x, behavior" in digest
    assert "selected_reference_citation_rate=0.333" in digest
    assert "## Memory governance" in digest
    assert "health_status=warn" in digest
    assert "untargeted_reference_count=5" in digest
    assert "broad-ref (broad-re)" in digest
    assert "noisy-ref" in digest
    assert "selected=2 cited=0 rate=0.000" in digest


@pytest.mark.asyncio
async def test_collect_improvement_signal_snapshot_scopes_queries_to_recent_project_signal_runs() -> None:
    from app.services.improvement_signals import collect_improvement_signal_snapshot

    now = datetime(2026, 3, 23, 12, 0, tzinfo=UTC)
    mock_db = AsyncMock()
    perf_result = MagicMock()
    perf_result.scalars.return_value.all.return_value = []
    experiment_result = MagicMock()
    experiment_result.all.return_value = []
    cluster_result = MagicMock()
    cluster_result.scalars.return_value.all.return_value = []
    event_result = MagicMock()
    event_result.all.return_value = []
    mock_db.execute.side_effect = [
        perf_result,
        experiment_result,
        cluster_result,
        event_result,
    ]

    @asynccontextmanager
    async def _session():
        yield mock_db

    memory_utilization = SimpleNamespace(
        injection_sessions=0,
        citation_sessions=0,
        lookup_sessions=0,
        lookup_after_injection_sessions=0,
        memory_search_calls=0,
        memory_get_calls=0,
        assistant_message_count=0,
        assistant_messages_with_memory_citations=0,
        citation_session_rate=0.0,
        lookup_session_rate=0.0,
        expansion_session_rate=0.0,
        assistant_citation_rate=0.0,
        sessions_with_selected_references=0,
        sessions_with_cited_selected_references=0,
        selected_reference_count=0,
        selected_reference_cited_count=0,
        selected_reference_citation_rate=0.0,
        selected_reference_session_rate=0.0,
        memory_inject_event_count=0,
        memory_inject_events_with_debug=0,
        memory_debug_coverage_rate=0.0,
    )

    with (
        patch("app.services.improvement_signals.async_session", return_value=_session()),
        patch(
            "app.services.improvement_signals.get_memory_utilization_summary",
            new=AsyncMock(return_value=memory_utilization),
        ),
        patch(
            "app.services.improvement_signals.collect_memory_governance_snapshot",
            new=AsyncMock(
                return_value={
                    "active_count": 0,
                    "by_context_kind": {},
                    "targeted_count": 0,
                    "explicit_exclusion_count": 0,
                    "untargeted_reference_count": 0,
                    "policy_with_targeting_count": 0,
                    "missing_reference_summary_count": 0,
                    "missing_capability_summary_count": 0,
                    "oversized_policy_count": 0,
                    "alias_trigger_task_type_count": 0,
                    "invalid_trigger_task_type_count": 0,
                    "invalid_trigger_task_type_samples": [],
                    "issue_count": 0,
                }
            ),
        ),
        patch(
            "app.services.improvement_signals.batch_get_episodes",
            new=AsyncMock(return_value={}),
        ),
        patch("app.services.improvement_signals.datetime") as mock_datetime,
    ):
        mock_datetime.now.return_value = now
        mock_datetime.UTC = UTC
        await collect_improvement_signal_snapshot(
            project_id="agent-hub",
            primary_agent_slug="persona",
            days_back=7,
        )

    experiment_stmt = mock_db.execute.await_args_list[1].args[0]
    cluster_stmt = mock_db.execute.await_args_list[2].args[0]

    experiment_compiled = experiment_stmt.compile(dialect=postgresql.dialect())
    experiment_sql = str(experiment_compiled)
    cluster_compiled = cluster_stmt.compile(dialect=postgresql.dialect())
    cluster_sql = str(cluster_compiled)

    assert "JOIN agent_benchmark_runs" in experiment_sql
    assert "agent_benchmark_runs.completed_at >=" in experiment_sql
    assert "agent_benchmark_runs.project_id" in experiment_sql
    assert "agent_benchmark_runs.run_kind" in experiment_sql
    assert "max(agent_benchmark_runs.completed_at)" in experiment_sql
    assert "agent-hub" in experiment_compiled.params.values()
    assert any(
        "honing_iteration" in (value if isinstance(value, list) else [value])
        for value in experiment_compiled.params.values()
    )

    assert "JOIN agent_benchmark_runs" in cluster_sql
    assert (
        "coalesce(agent_regression_clusters.last_seen_run_id, "
        "agent_regression_clusters.first_seen_run_id)"
    ) in cluster_sql
    assert "agent_regression_clusters.last_seen_at >=" in cluster_sql
    assert "agent_benchmark_runs.project_id" in cluster_sql
    assert "agent_benchmark_runs.run_kind" in cluster_sql
    assert "agent-hub" in cluster_compiled.params.values()
    assert any(
        "honing_iteration" in (value if isinstance(value, list) else [value])
        for value in cluster_compiled.params.values()
    )
