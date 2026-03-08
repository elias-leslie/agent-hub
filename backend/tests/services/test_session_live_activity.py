from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from app.services.session_live_activity import build_live_activity_response


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
