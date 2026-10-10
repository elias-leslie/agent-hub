"""Tests for persona improvement field scoring."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.models import SessionEventType
from app.services.persona_improvement import (
    _heartbeat_issue_codes_from_events,
    _heartbeat_result_status,
    _score_heartbeat_session,
    _summarize_heartbeat_field_sessions,
    evaluate_persona_heartbeat_field_snapshot,
    get_persona_heartbeat_field_snapshot,
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
            "top_issue_count": 0,
            "unknown_heartbeats": 0,
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


def test_evaluate_persona_heartbeat_field_snapshot_flags_repeated_issue() -> None:
    snapshot = {
        "overview": {
            "reliability": 93.0,
            "truth_quality": 92.0,
            "critical_heartbeats": 0,
            "partial_rate": 0.0,
            "partial_heartbeats": 0,
            "top_issue_count": 4,
            "unknown_heartbeats": 1,
        },
        "recent_heartbeats": [{"session_id": "sess-1"}],
    }

    result = evaluate_persona_heartbeat_field_snapshot(snapshot)

    assert result["needs_review"] is True
    assert result["reason_codes"] == [
        "field_repeated_issue",
    ]
    assert "repeated field issue needs a source fix" in result["summary"]


def test_evaluate_persona_heartbeat_field_snapshot_flags_partial_churn() -> None:
    snapshot = {
        "overview": {
            "reliability": 92.0,
            "truth_quality": 96.0,
            "critical_heartbeats": 0,
            "partial_rate": 82.0,
            "partial_heartbeats": 9,
            "top_issue_count": 0,
            "unknown_heartbeats": 0,
        },
        "recent_heartbeats": [{"session_id": "sess-1"}],
    }

    result = evaluate_persona_heartbeat_field_snapshot(snapshot)

    assert result["needs_review"] is True
    assert result["reason_codes"] == [
        "field_partial_churn",
    ]
    assert "partial heartbeat rate above review ceiling" in result["summary"]


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
                "result_status": "ok",
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
                "result_status": "unknown",
            },
        ]
    )

    assert summary["healthy_heartbeats"] == 1
    assert summary["healthy_rate"] == 33.3
    assert summary["action_heartbeats"] == 0
    assert summary["action_rate"] == 0.0
    assert summary["ok_heartbeats"] == 1
    assert summary["ok_rate"] == 33.3
    assert summary["partial_heartbeats"] == 1
    assert summary["partial_rate"] == 33.3
    assert summary["completed_heartbeats"] == 0
    assert summary["failed_heartbeats"] == 0
    assert summary["unknown_heartbeats"] == 1
    assert summary["top_issue_code"] == "cleanup_actionable"
    assert summary["top_issue_label"] == "cleanup still actionable"
    assert summary["top_issue_count"] == 2


def test_heartbeat_result_status_prefers_partial_summary_tag_over_ok_prefix() -> None:
    content = (
        "HEARTBEAT_OK queue checked.\n"
        "[[S:partial:Confirmed only manual-project ready tasks remain undispatchable.]]"
    )

    result = _heartbeat_result_status(content, "completed")

    assert result == "partial"


def test_heartbeat_issue_codes_from_events_flags_unrecovered_cli_usage_error() -> None:
    issue_codes = _heartbeat_issue_codes_from_events(
        [
            (SessionEventType.TOOL_USE, "$ st cleanup status --project agent-hub"),
            (
                SessionEventType.TOOL_RESULT,
                "Usage: st cleanup status [OPTIONS]\nTry 'st cleanup status --help' for help.\n\nError: No such option: --project",
            ),
            (SessionEventType.TOOL_USE, '{"action":"overview"}'),
        ]
    )

    assert issue_codes == ["cli_usage_error"]


def test_heartbeat_issue_codes_from_events_clears_cli_usage_error_after_help() -> None:
    issue_codes = _heartbeat_issue_codes_from_events(
        [
            (SessionEventType.TOOL_USE, "$ st cleanup status --project agent-hub"),
            (
                SessionEventType.TOOL_RESULT,
                "Usage: st cleanup status [OPTIONS]\nTry 'st cleanup status --help' for help.\n\nError: No such option: --project",
            ),
            (SessionEventType.TOOL_USE, "$ st cleanup status --help"),
            (SessionEventType.TOOL_RESULT, "Usage: st cleanup status [OPTIONS]\n\nOptions:\n  --all"),
        ]
    )

    assert issue_codes == []


def test_heartbeat_issue_codes_from_events_flags_dispatch_not_ready() -> None:
    issue_codes = _heartbeat_issue_codes_from_events(
        [
            (SessionEventType.TOOL_USE, '{"action":"dispatch","task_id":"task-76d306d6"}'),
            (
                SessionEventType.TOOL_RESULT,
                "ERROR Task task-76d306d6 is not execution-ready for autocode.",
            ),
        ]
    )

    assert issue_codes == ["dispatch_not_ready"]


def test_score_heartbeat_session_marks_partial_outcome_unhealthy() -> None:
    reliability, effectiveness, truth_quality, healthy = _score_heartbeat_session(
        session_status="completed",
        issue_codes=[],
        result_status="partial",
    )

    assert reliability == 100.0
    assert effectiveness == 65.0
    assert truth_quality == 100.0
    assert healthy is False


@pytest.mark.asyncio
async def test_field_snapshot_uses_full_window_for_overview_and_limit_for_recent_items() -> None:
    sessions = [
        {
            "session_id": "sess-1",
            "completed_at": "2026-04-01T12:00:00+00:00",
            "created_at": "2026-04-01T11:59:00+00:00",
            "status": "completed",
            "result_status": "action",
            "summary_oneliner": "moved work",
            "reliability": 100.0,
            "effectiveness": 100.0,
            "truth_quality": 100.0,
            "total_tokens": 100,
            "input_tokens": 60,
            "output_tokens": 40,
            "tool_calls": 1,
            "turns": 1,
            "issue_codes": [],
            "issue_summary": "clean",
            "healthy": True,
        },
        {
            "session_id": "sess-2",
            "completed_at": "2026-04-01T11:00:00+00:00",
            "created_at": "2026-04-01T10:59:00+00:00",
            "status": "completed",
            "result_status": "ok",
            "summary_oneliner": "clean idle",
            "reliability": 100.0,
            "effectiveness": 100.0,
            "truth_quality": 100.0,
            "total_tokens": 80,
            "input_tokens": 50,
            "output_tokens": 30,
            "tool_calls": 1,
            "turns": 1,
            "issue_codes": [],
            "issue_summary": "clean",
            "healthy": True,
        },
        {
            "session_id": "sess-3",
            "completed_at": "2026-04-01T10:00:00+00:00",
            "created_at": "2026-04-01T09:59:00+00:00",
            "status": "completed",
            "result_status": "unknown",
            "summary_oneliner": "needs review",
            "reliability": 70.0,
            "effectiveness": 70.0,
            "truth_quality": 75.0,
            "total_tokens": 90,
            "input_tokens": 60,
            "output_tokens": 30,
            "tool_calls": 2,
            "turns": 2,
            "issue_codes": ["cleanup_actionable"],
            "issue_summary": "cleanup still actionable",
            "healthy": False,
        },
    ]

    with patch(
        "app.services.persona_improvement._collect_heartbeat_field_sessions",
        new=AsyncMock(return_value=sessions),
    ):
        snapshot = await get_persona_heartbeat_field_snapshot(AsyncMock(), days=7, limit=2)

    assert snapshot["overview"]["total_heartbeats"] == 3
    assert snapshot["overview"]["unknown_heartbeats"] == 1
    assert len(snapshot["recent_heartbeats"]) == 2
    assert [item["session_id"] for item in snapshot["recent_heartbeats"]] == ["sess-1", "sess-2"]
    assert [point["session_id"] for point in snapshot["trend"]] == ["sess-2", "sess-1"]
