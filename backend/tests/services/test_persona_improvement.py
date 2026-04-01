"""Tests for Jenny improvement service field scoring and schedule defaults."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.persona_improvement import (
    DEFAULT_SELF_HONING_CADENCE_MINUTES,
    _summarize_heartbeat_field_sessions,
    evaluate_persona_heartbeat_field_snapshot,
    get_persona_improvement_dashboard,
    serialize_persona_self_honing_schedule,
)


def test_evaluate_persona_heartbeat_field_snapshot_allows_clean_recent_field_data() -> None:
    snapshot = {
        "overview": {
            "reliability": 94.0,
            "truth_quality": 96.0,
            "critical_heartbeats": 0,
        },
        "recent_heartbeats": [{"session_id": "sess-1"}],
    }

    result = evaluate_persona_heartbeat_field_snapshot(snapshot)

    assert result == {
        "needs_review": False,
        "reason_codes": [],
        "summary": "field_ok",
    }


def test_evaluate_persona_heartbeat_field_snapshot_flags_critical_or_low_quality_field_data() -> None:
    snapshot = {
        "overview": {
            "reliability": 82.0,
            "truth_quality": 80.0,
            "critical_heartbeats": 1,
        },
        "recent_heartbeats": [{"session_id": "sess-1"}],
    }

    result = evaluate_persona_heartbeat_field_snapshot(snapshot)

    assert result["needs_review"] is True
    assert result["reason_codes"] == [
        "critical_heartbeat_failures",
        "field_reliability_low",
        "field_truth_quality_low",
    ]
    assert "recent critical heartbeat failures" in result["summary"]


def test_summarize_heartbeat_field_sessions_tracks_completion_mix_and_top_issue() -> None:
    summary = _summarize_heartbeat_field_sessions(
        [
            {
                "reliability": 100.0,
                "effectiveness": 100.0,
                "truth_quality": 100.0,
                "healthy": True,
                "total_tokens": 100,
                "tool_calls": 1,
                "turns": 1,
                "issue_codes": [],
                "completed_at": "2026-04-01T12:00:00+00:00",
                "result_status": "completed",
            },
            {
                "reliability": 65.0,
                "effectiveness": 65.0,
                "truth_quality": 70.0,
                "healthy": False,
                "total_tokens": 90,
                "tool_calls": 2,
                "turns": 2,
                "issue_codes": ["cleanup_actionable", "missing_progress"],
                "completed_at": "2026-04-01T11:45:00+00:00",
                "result_status": "partial",
            },
            {
                "reliability": 70.0,
                "effectiveness": 70.0,
                "truth_quality": 75.0,
                "healthy": False,
                "total_tokens": 80,
                "tool_calls": 2,
                "turns": 2,
                "issue_codes": ["cleanup_actionable"],
                "completed_at": "2026-04-01T11:30:00+00:00",
                "result_status": "partial",
            },
        ]
    )

    assert summary["completed_heartbeats"] == 1
    assert summary["partial_heartbeats"] == 2
    assert summary["failed_heartbeats"] == 0
    assert summary["top_issue_code"] == "cleanup_actionable"
    assert summary["top_issue_label"] == "cleanup still actionable"
    assert summary["top_issue_count"] == 2


def test_serialize_persona_self_honing_schedule_defaults_to_15_minutes() -> None:
    result = serialize_persona_self_honing_schedule(None)

    assert DEFAULT_SELF_HONING_CADENCE_MINUTES == 15
    assert result["enabled"] is False
    assert result["cadence_minutes"] == 15
    assert result["cadence_label"] == "15m"
    assert result["schedule_value"] == str(15 * 60000)


@pytest.mark.asyncio
async def test_dashboard_includes_latest_honing_iteration_run() -> None:
    now = datetime.now(UTC)
    latest_run = SimpleNamespace(
        id="run-iter",
        benchmark_id="persona-benchmark-latest",
        suite_id="persona-suite-jenny-improvement",
        run_kind="honing_iteration",
        started_at=now - timedelta(minutes=2),
        completed_at=now,
        models=["codex/gpt-5.4"],
        case_ids=["manual_project_access_block"],
        attempt_count=1,
        passed_attempt_count=1,
        infra_failure_count=0,
        pass_rate=100.0,
        avg_score=100.0,
        run_metadata={
            "persona_improvement": {
                "reliability": 100.0,
                "effectiveness": 100.0,
                "avg_total_tokens": 500.0,
                "tokens_per_passed_attempt": 500.0,
                "avg_tool_calls": 0.0,
                "avg_turns": 1.0,
                "prompt_tokens": 1234,
                "failure_count": 0,
                "top_failure_detail": None,
                "family_breakdown": [],
            }
        },
        config_snapshot={},
        experiment_id=None,
    )
    older_candidate = SimpleNamespace(
        id="run-old",
        benchmark_id="persona-benchmark-old",
        suite_id="persona-suite-jenny-improvement",
        run_kind="honing_candidate",
        started_at=now - timedelta(hours=1, minutes=2),
        completed_at=now - timedelta(hours=1),
        models=["codex/gpt-5.4"],
        case_ids=["manual_project_access_block"],
        attempt_count=1,
        passed_attempt_count=0,
        infra_failure_count=0,
        pass_rate=0.0,
        avg_score=0.0,
        run_metadata={
            "persona_improvement": {
                "reliability": 0.0,
                "effectiveness": 0.0,
                "avg_total_tokens": 900.0,
                "tokens_per_passed_attempt": None,
                "avg_tool_calls": 0.0,
                "avg_turns": 1.0,
                "prompt_tokens": 1234,
                "failure_count": 1,
                "top_failure_detail": "wrong_fields: primary_action",
                "family_breakdown": [],
            }
        },
        config_snapshot={},
        experiment_id=None,
    )

    class _ScalarResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def all(self):
            return self._rows

    mock_db = AsyncMock()
    mock_db.execute.return_value = _ScalarResult([latest_run, older_candidate])

    with (
        patch(
            "app.services.persona_improvement.get_persona_self_honing_job",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.persona_improvement.query_open_regression_clusters",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.persona_improvement.get_persona_heartbeat_field_snapshot",
            new=AsyncMock(
                return_value={
                    "overview": {
                        "total_heartbeats": 1,
                        "latest_completed_at": now.isoformat(),
                        "reliability": 100.0,
                        "effectiveness": 100.0,
                        "truth_quality": 100.0,
                        "tokens_per_healthy_heartbeat": 100.0,
                        "avg_tool_calls": 1.0,
                        "avg_turns": 1.0,
                        "risky_heartbeats": 0,
                        "critical_heartbeats": 0,
                    },
                    "trend": [],
                    "recent_heartbeats": [],
                    "risks": [],
                }
            ),
        ),
    ):
        payload = await get_persona_improvement_dashboard(mock_db, days=30, limit=8)

    assert payload["overview"]["latest_completed_at"] == latest_run.completed_at.isoformat()
    assert payload["latest_lab_run"]["run_id"] == "run-iter"
    assert payload["latest_lab_run"]["reliability"] == 100.0
    assert payload["recent_runs"][0]["run_id"] == "run-iter"
    assert payload["recent_runs"][0]["run_kind"] == "honing_iteration"


@pytest.mark.asyncio
async def test_dashboard_current_lab_run_prefers_baseline_when_latest_candidate_was_held() -> None:
    now = datetime.now(UTC)
    experiment = SimpleNamespace(
        id="exp-1",
        decision="hold",
        decision_reason="no_clear_winner",
        evidence={"final_decision_source": "benchmark"},
    )
    latest_candidate = SimpleNamespace(
        id="run-candidate",
        benchmark_id="persona-benchmark-candidate",
        suite_id="persona-suite-jenny-improvement",
        run_kind="honing_candidate",
        started_at=now - timedelta(minutes=2),
        completed_at=now,
        models=["codex/gpt-5.4"],
        case_ids=["manual_project_access_block"],
        attempt_count=1,
        passed_attempt_count=1,
        infra_failure_count=0,
        pass_rate=100.0,
        avg_score=100.0,
        run_metadata={
            "persona_improvement": {
                "reliability": 100.0,
                "effectiveness": 100.0,
                "avg_total_tokens": 400.0,
                "tokens_per_passed_attempt": 400.0,
                "avg_tool_calls": 0.0,
                "avg_turns": 1.0,
                "prompt_tokens": 1500,
                "failure_count": 0,
                "top_failure_detail": None,
                "family_breakdown": [],
            }
        },
        config_snapshot={},
        experiment_id="exp-1",
    )
    paired_baseline = SimpleNamespace(
        id="run-baseline",
        benchmark_id="persona-benchmark-baseline",
        suite_id="persona-suite-jenny-improvement",
        run_kind="honing_baseline",
        started_at=now - timedelta(minutes=4),
        completed_at=now - timedelta(minutes=1),
        models=["codex/gpt-5.4"],
        case_ids=["manual_project_access_block"],
        attempt_count=1,
        passed_attempt_count=1,
        infra_failure_count=0,
        pass_rate=100.0,
        avg_score=100.0,
        run_metadata={
            "persona_improvement": {
                "reliability": 97.0,
                "effectiveness": 98.0,
                "avg_total_tokens": 500.0,
                "tokens_per_passed_attempt": 500.0,
                "avg_tool_calls": 0.0,
                "avg_turns": 1.0,
                "prompt_tokens": 1400,
                "failure_count": 0,
                "top_failure_detail": None,
                "family_breakdown": [],
            }
        },
        config_snapshot={},
        experiment_id="exp-1",
    )

    class _ScalarResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def all(self):
            return self._rows

    mock_db = AsyncMock()
    mock_db.execute.side_effect = [
        _ScalarResult([latest_candidate, paired_baseline]),
        _ScalarResult([experiment]),
    ]

    with (
        patch(
            "app.services.persona_improvement.get_persona_self_honing_job",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.persona_improvement.query_open_regression_clusters",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.persona_improvement.get_persona_heartbeat_field_snapshot",
            new=AsyncMock(
                return_value={
                    "overview": {
                        "total_heartbeats": 1,
                        "latest_completed_at": now.isoformat(),
                        "reliability": 100.0,
                        "effectiveness": 100.0,
                        "truth_quality": 100.0,
                        "tokens_per_healthy_heartbeat": 100.0,
                        "avg_tool_calls": 1.0,
                        "avg_turns": 1.0,
                        "risky_heartbeats": 0,
                        "critical_heartbeats": 0,
                    },
                    "trend": [],
                    "recent_heartbeats": [],
                    "risks": [],
                }
            ),
        ),
    ):
        payload = await get_persona_improvement_dashboard(mock_db, days=30, limit=8)

    assert payload["recent_runs"][0]["run_id"] == "run-candidate"
    assert payload["recent_runs"][0]["experiment_decision"] == "hold"
    assert payload["latest_lab_run"]["run_id"] == "run-baseline"
    assert payload["latest_lab_run"]["reliability"] == 97.0


@pytest.mark.asyncio
async def test_dashboard_flags_overdue_self_honing_schedule() -> None:
    now = datetime.now(UTC)

    class _ScalarResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def all(self):
            return self._rows

    mock_db = AsyncMock()
    mock_db.execute.return_value = _ScalarResult([])

    overdue_job = SimpleNamespace(
        id="job-1",
        enabled=True,
        schedule_type="every",
        schedule_value=str(15 * 60 * 1000),
        schedule_timezone="UTC",
        last_run_at=now - timedelta(minutes=30),
        next_run_at=now - timedelta(minutes=10),
        run_count=4,
    )

    with (
        patch(
            "app.services.persona_improvement.get_persona_self_honing_job",
            new=AsyncMock(return_value=overdue_job),
        ),
        patch(
            "app.services.persona_improvement.query_open_regression_clusters",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.persona_improvement.get_persona_heartbeat_field_snapshot",
            new=AsyncMock(
                return_value={
                    "overview": {
                        "total_heartbeats": 0,
                        "latest_completed_at": None,
                        "reliability": None,
                        "effectiveness": None,
                        "truth_quality": None,
                        "tokens_per_healthy_heartbeat": None,
                        "avg_tool_calls": None,
                        "avg_turns": None,
                        "risky_heartbeats": 0,
                        "critical_heartbeats": 0,
                    },
                    "trend": [],
                    "recent_heartbeats": [],
                    "risks": [],
                }
            ),
        ),
    ):
        payload = await get_persona_improvement_dashboard(mock_db, days=30, limit=8)

    assert payload["schedule_risks"] == [
        {
            "kind": "schedule_overdue",
            "summary": "Scheduled self-improvement is overdue.",
            "detail": f"next run was due at {overdue_job.next_run_at.isoformat()}",
            "critical": True,
        }
    ]


@pytest.mark.asyncio
async def test_dashboard_allows_scheduler_polling_grace_before_flagging_overdue_schedule() -> None:
    now = datetime.now(UTC)

    class _ScalarResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def all(self):
            return self._rows

    mock_db = AsyncMock()
    mock_db.execute.return_value = _ScalarResult([])

    just_due_job = SimpleNamespace(
        id="job-1",
        enabled=True,
        schedule_type="every",
        schedule_value=str(15 * 60 * 1000),
        schedule_timezone="UTC",
        last_run_at=now - timedelta(minutes=18),
        next_run_at=now - timedelta(minutes=3),
        run_count=4,
    )

    with (
        patch(
            "app.services.persona_improvement.get_persona_self_honing_job",
            new=AsyncMock(return_value=just_due_job),
        ),
        patch(
            "app.services.persona_improvement.query_open_regression_clusters",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.persona_improvement.get_persona_heartbeat_field_snapshot",
            new=AsyncMock(
                return_value={
                    "overview": {
                        "total_heartbeats": 0,
                        "latest_completed_at": None,
                        "reliability": None,
                        "effectiveness": None,
                        "truth_quality": None,
                        "tokens_per_healthy_heartbeat": None,
                        "avg_tool_calls": None,
                        "avg_turns": None,
                        "risky_heartbeats": 0,
                        "critical_heartbeats": 0,
                    },
                    "trend": [],
                    "recent_heartbeats": [],
                    "risks": [],
                }
            ),
        ),
    ):
        payload = await get_persona_improvement_dashboard(mock_db, days=30, limit=8)

    assert payload["schedule_risks"] == []
