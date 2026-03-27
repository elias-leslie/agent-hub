from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from app.services.session_live_activity import (
    apply_live_activity_heartbeat,
    build_live_activity_response,
)


def test_build_live_activity_response_keeps_short_post_tool_wait_quiet() -> None:
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
    assert response["health"] == "quiet"
    assert response["stalled"] is False


def test_build_live_activity_response_marks_long_active_wait_as_stalled() -> None:
    session = MagicMock()
    session.status = "active"
    session.provider_metadata = {
        "live_activity": {
            "phase": "waiting_for_model",
            "status": "active",
            "summary": "Waiting for model after Bash",
            "last_event_type": "tool_result",
            "last_event_at": (datetime.now(UTC) - timedelta(minutes=31)).isoformat(),
            "last_model_activity_at": (datetime.now(UTC) - timedelta(minutes=31)).isoformat(),
            "outstanding_tool_calls": 0,
            "tool_calls_count": 2,
        }
    }

    response = build_live_activity_response(session)

    assert response is not None
    assert response["health"] == "stalled"
    assert response["stalled"] is True
    assert response["stall_reason"] == "No model activity for 1860s while phase=waiting_for_model"


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


def test_build_live_activity_response_marks_heartbeat_only_session_dead_candidate() -> None:
    session = MagicMock()
    session.status = "active"
    session.provider_metadata = {
        "live_activity": {
            "phase": "waiting_for_model",
            "status": "active",
            "summary": "Transcript sync heartbeat",
            "last_event_type": "heartbeat",
            "last_event_at": (datetime.now(UTC) - timedelta(minutes=45)).isoformat(),
            "last_model_activity_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
            "outstanding_tool_calls": 0,
            "tool_calls_count": 2,
            "last_heartbeat_at": datetime.now(UTC).isoformat(),
        }
    }

    response = build_live_activity_response(session)

    assert response is not None
    assert response["lifecycle_state"] == "dead_candidate"
    assert "heartbeat_only" in response["dead_signals"]
    assert response["reapable"] is False


def test_build_live_activity_response_marks_lane_free_heartbeat_only_session_reapable() -> None:
    session = MagicMock()
    session.status = "active"
    session.provider_metadata = {
        "live_activity": {
            "phase": "waiting_for_model",
            "status": "active",
            "summary": "Transcript sync heartbeat",
            "last_event_type": "heartbeat",
            "last_event_at": (datetime.now(UTC) - timedelta(minutes=45)).isoformat(),
            "last_model_activity_at": (datetime.now(UTC) - timedelta(hours=7)).isoformat(),
            "outstanding_tool_calls": 0,
            "tool_calls_count": 2,
            "last_heartbeat_at": datetime.now(UTC).isoformat(),
        }
    }

    response = build_live_activity_response(session, has_owner_lane=False, has_specialist_lane=False)

    assert response is not None
    assert response["lifecycle_state"] == "reapable"
    assert response["reapable"] is True
    assert response["reapable_reason"] == "no_model_activity_30m+heartbeat_only+no_lane"


def test_build_live_activity_response_marks_stale_untracked_session_reapable() -> None:
    session = MagicMock()
    session.status = "active"
    session.provider_metadata = {}
    session.updated_at = datetime.now(UTC) - timedelta(hours=7)
    session.last_activity_at = None
    session.created_at = datetime.now(UTC) - timedelta(hours=8)

    response = build_live_activity_response(session)

    assert response is not None
    assert response["phase"] == "unknown"
    assert response["lifecycle_state"] == "reapable"
    assert "no_structured_activity" in response["dead_signals"]
    assert response["reapable_reason"] == "no_model_activity_30m+no_structured_activity+heartbeat_missing+no_lane"


def test_build_live_activity_response_blocks_reaping_when_lane_is_active() -> None:
    session = MagicMock()
    session.status = "active"
    session.provider_metadata = {
        "live_activity": {
            "phase": "waiting_for_model",
            "status": "active",
            "summary": "Transcript sync heartbeat",
            "last_event_type": "heartbeat",
            "last_event_at": (datetime.now(UTC) - timedelta(minutes=45)).isoformat(),
            "last_model_activity_at": (datetime.now(UTC) - timedelta(hours=7)).isoformat(),
            "outstanding_tool_calls": 0,
            "tool_calls_count": 2,
            "last_heartbeat_at": datetime.now(UTC).isoformat(),
        }
    }

    response = build_live_activity_response(session, has_owner_lane=True)

    assert response is not None
    assert response["lifecycle_state"] == "dead_candidate"
    assert response["reapable"] is False
    assert "owner_lane" in response["anti_reap_signals"]


def test_build_live_activity_response_reaps_stale_detached_rebuild_specialist_session() -> None:
    session = MagicMock()
    session.status = "active"
    session.provider_metadata = {
        "live_activity": {
            "phase": "waiting_for_model",
            "status": "active",
            "summary": "Waiting for model after bash",
            "last_event_type": "tool_result",
            "last_event_at": (datetime.now(UTC) - timedelta(minutes=31)).isoformat(),
            "last_model_activity_at": (datetime.now(UTC) - timedelta(minutes=31)).isoformat(),
            "outstanding_tool_calls": 0,
            "tool_calls_count": 8,
            "last_command": "cd /srv/workspaces/projects/agent-hub && rebuild.sh --detach agent-hub",
        }
    }

    response = build_live_activity_response(session, has_owner_lane=False, has_specialist_lane=True)

    assert response is not None
    assert response["lifecycle_state"] == "reapable"
    assert response["reapable"] is True
    assert "detached_control_plane_rebuild" in response["dead_signals"]
    assert "specialist_lane" not in response["anti_reap_signals"]


def test_build_live_activity_response_reaps_lane_free_stale_finalizing_session() -> None:
    session = MagicMock()
    session.status = "active"
    session.provider_metadata = {
        "live_activity": {
            "phase": "finalizing",
            "status": "active",
            "summary": "Assistant responded with final summary",
            "last_event_type": "assistant_message",
            "last_event_at": (datetime.now(UTC) - timedelta(hours=7)).isoformat(),
            "last_model_activity_at": (datetime.now(UTC) - timedelta(hours=7)).isoformat(),
            "outstanding_tool_calls": 0,
            "tool_calls_count": 8,
        }
    }

    response = build_live_activity_response(session, has_owner_lane=False, has_specialist_lane=False)

    assert response is not None
    assert response["lifecycle_state"] == "reapable"
    assert response["reapable"] is True
    assert "phase_finalizing" not in response["anti_reap_signals"]
