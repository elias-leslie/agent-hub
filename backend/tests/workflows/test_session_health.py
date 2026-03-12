from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.workflows._heartbeat_data import (
    _fetch_active_sessions_section,
    _format_active_session_entry,
    _session_display_health,
    _session_stale_threshold_minutes,
)


class TestSessionHealthThresholds:
    def test_coding_agents_get_longer_stale_threshold(self) -> None:
        assert _session_stale_threshold_minutes(True) == 30

    def test_other_agents_use_default_stale_threshold(self) -> None:
        assert _session_stale_threshold_minutes(False) == 15
        assert _session_stale_threshold_minutes(None) == 15


class TestSessionHealthFormatting:
    def test_stale_sessions_render_idle_label_when_not_in_flight(self) -> None:
        assert _session_display_health("processing_response", is_stale=True) == "idle"

    def test_stale_in_flight_sessions_keep_phase_visible(self) -> None:
        assert _session_display_health("calling_model", is_stale=True) == "calling_model"
        assert _session_display_health("executing_tool:Bash", is_stale=True) == "executing_tool:Bash"

    def test_active_sessions_render_current_health_detail(self) -> None:
        assert _session_display_health("executing_tool:Bash", is_stale=False) == "executing_tool:Bash"
        assert _session_display_health(None, is_stale=False) == "idle"

    def test_format_active_session_entry_includes_health_age_turn_and_stale_flag(self) -> None:
        now = datetime(2026, 3, 12, 0, 0, tzinfo=UTC)
        entry = _format_active_session_entry(
            {
                "agent_slug": "refactor",
                "task_ref": "task-def",
                "health_detail": "processing_response",
                "last_activity_at": now - timedelta(minutes=28),
                "turn_count": 3,
                "is_stale": True,
            },
            now=now,
        )

        assert entry == "- refactor | task-def | idle | 28m ago | turn 3 | STALE"


class TestActiveSessionsSection:
    @pytest.mark.asyncio
    async def test_fetch_active_sessions_section_uses_enriched_session_rows(self) -> None:
        now = datetime.now(UTC)
        fake_rows = [
            {
                "agent_slug": "coder",
                "task_ref": "task-abc",
                "health_detail": "executing_tool:Bash",
                "last_activity_at": now - timedelta(minutes=2),
                "turn_count": 12,
                "is_stale": False,
            },
            {
                "agent_slug": "analyst",
                "task_ref": "task-ghi",
                "health_detail": "calling_model",
                "last_activity_at": now - timedelta(minutes=2),
                "turn_count": 1,
                "is_stale": False,
            },
        ]

        with patch(
            "app.workflows._heartbeat_data._query_active_sessions_for_heartbeat",
            new=AsyncMock(return_value=fake_rows),
        ):
            result = await _fetch_active_sessions_section()

        assert "Active agent sessions: 2" in result
        assert "- coder | task-abc | executing_tool:Bash | 2m ago | turn 12" in result
        assert "- analyst | task-ghi | calling_model | 2m ago | turn 1" in result
