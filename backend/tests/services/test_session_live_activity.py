from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from app.services.session_live_activity import (
    apply_live_activity_heartbeat,
    build_live_activity_response,
)


def test_build_live_activity_response_marks_post_tool_wait_as_stalled_earlier() -> None:
    session = MagicMock()
    session.status = "active"
    session.provider_metadata = {
        "live_activity": {
            "phase": "waiting_for_model",
            "status": "active",
            "summary": "Waiting for model after Read",
            "last_event_type": "tool_result",
            "last_event_at": (datetime.now(UTC) - timedelta(seconds=125)).isoformat(),
            "last_model_activity_at": (datetime.now(UTC) - timedelta(seconds=125)).isoformat(),
            "outstanding_tool_calls": 0,
            "tool_calls_count": 1,
        }
    }

    response = build_live_activity_response(session)

    assert response is not None
    assert response["health"] == "stalled"
    assert response["stalled"] is True
    assert response["stall_reason"] == "No model activity for 125s after tool_result"


def test_build_live_activity_response_keeps_short_post_tool_wait_quiet() -> None:
    session = MagicMock()
    session.status = "active"
    session.provider_metadata = {
        "live_activity": {
            "phase": "waiting_for_model",
            "status": "active",
            "summary": "Waiting for model after Bash",
            "last_event_type": "tool_result",
            "last_event_at": (datetime.now(UTC) - timedelta(seconds=70)).isoformat(),
            "last_model_activity_at": (datetime.now(UTC) - timedelta(seconds=70)).isoformat(),
            "outstanding_tool_calls": 0,
            "tool_calls_count": 2,
        }
    }

    response = build_live_activity_response(session)

    assert response is not None
    assert response["health"] == "quiet"
    assert response["stalled"] is False


def test_apply_live_activity_heartbeat_tracks_recent_paths() -> None:
    session = MagicMock()
    session.provider_metadata = {}

    apply_live_activity_heartbeat(
        session,
        heartbeat_at="2026-03-10T14:00:00+00:00",
        phase="running_tool",
        status="active",
        summary="Editing ownership inventory",
        current_tool_name="Write",
        current_command="Write backend/app/services/ownership_inventory.py",
        last_event_type="tool_result",
        active_read_paths=["backend/app/services/session_live_activity.py"],
        active_write_paths=["backend/app/services/ownership_inventory.py"],
    )

    live = session.provider_metadata["live_activity"]
    assert live["last_heartbeat_at"] == "2026-03-10T14:00:00+00:00"
    assert live["current_tool_name"] == "Write"
    assert live["current_command"] == "Write backend/app/services/ownership_inventory.py"
    assert live["recent_read_paths"] == ["backend/app/services/session_live_activity.py"]
    assert live["recent_write_paths"] == ["backend/app/services/ownership_inventory.py"]


def test_build_live_activity_response_normalizes_completed_sessions_with_stale_active_state() -> None:
    session = MagicMock()
    session.status = "completed"
    session.provider_metadata = {
        "live_activity": {
            "phase": "waiting_for_model",
            "status": "active",
            "summary": "Waiting for model after Bash",
            "last_event_type": "tool_result",
            "last_event_at": (datetime.now(UTC) - timedelta(seconds=70)).isoformat(),
            "last_model_activity_at": (datetime.now(UTC) - timedelta(seconds=70)).isoformat(),
            "outstanding_tool_calls": 0,
            "tool_calls_count": 2,
        }
    }

    response = build_live_activity_response(session)

    assert response is not None
    assert response["phase"] == "completed"
    assert response["status"] == "completed"
    assert response["summary"] == "Session completed"
    assert response["health"] == "completed"
