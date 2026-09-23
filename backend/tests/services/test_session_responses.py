"""Tests for session response helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.session import SessionEvent
from app.services.session_responses import _resolve_agent_display_names, build_event_responses


def test_native_event_response_exposes_source_and_usage() -> None:
    timestamp = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)
    event = SessionEvent(
        id="e2f26650-4e67-4302-905f-c17e7071f337",
        session_id="session-1",
        turn=1,
        sequence=1,
        event_type="usage",
        call_id="call-1",
        source_event_id="response_usage:resp-1:1",
        source_timestamp=timestamp,
        usage={"scope": "response", "source": "codex.token_usage_record.usage", "input_tokens": 10},
        created_at=timestamp,
    )

    response = build_event_responses([event])[0]

    assert response.source_event_id == "response_usage:resp-1:1"
    assert response.call_id == "call-1"
    assert response.source_timestamp == timestamp
    assert response.usage == event.usage


class TestResolveAgentDisplayNames:
    @pytest.mark.asyncio
    async def test_prefers_persona_display_name_from_persona_row(self) -> None:
        events = [
            SimpleNamespace(agent_id="persona", agent_name=None),
            SimpleNamespace(agent_id="coder", agent_name="coder"),
        ]
        agent_rows = MagicMock()
        agent_rows.all.return_value = [
            SimpleNamespace(slug="persona", name="Legacy Persona"),
            SimpleNamespace(slug="coder", name="Coder"),
        ]
        persona_name = MagicMock()
        persona_name.scalar_one_or_none.return_value = "Renamed Persona"

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[agent_rows, persona_name])

        result = await _resolve_agent_display_names(db, events)

        assert result["persona"] == "Renamed Persona"
        assert result["coder"] == "Coder"
