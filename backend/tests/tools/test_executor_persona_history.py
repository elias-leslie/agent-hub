"""Tests for bounded persona history recall tooling."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.tools._executor_persona_history import search_persona_history


@pytest.mark.asyncio
async def test_search_persona_history_returns_compact_matches_with_topic() -> None:
    mock_db = AsyncMock()

    @asynccontextmanager
    async def _session():
        yield mock_db

    entry = SimpleNamespace(
        id="session-sess-1",
        timestamp=datetime(2026, 3, 31, 12, 0, tzinfo=UTC),
        entry_type="heartbeat",
        project_id="agent-hub",
        agent_slug="persona",
        status="completed",
        live_status="completed",
        live_topic="task:task-123",
        external_id="task-123",
        current_branch="task-123/main",
        session_id="sess-1",
    )
    match = SimpleNamespace(
        entry_id="session-sess-1",
        session_id="sess-1",
        snippet="Closed the task checkpoint after validation.",
    )

    with (
        patch("app.db.async_session", _session),
        patch(
            "app.services.tools._executor_persona_history._fetch_sessions",
            new_callable=AsyncMock,
            return_value=([SimpleNamespace(id="sess-1", session_type="heartbeat")], []),
        ),
        patch(
            "app.services.tools._executor_persona_history._fetch_event_counts",
            new_callable=AsyncMock,
            side_effect=[{"sess-1": 1}, {"sess-1": 2}],
        ),
        patch(
            "app.services.tools._executor_persona_history._fetch_event_previews",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "app.services.tools._executor_persona_history._fetch_persona_chat_events",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.services.tools._executor_persona_history._fetch_display_summaries",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "app.services.tools._executor_persona_history.build_session_pulses",
            return_value={},
        ),
        patch(
            "app.services.tools._executor_persona_history._build_stream_entries",
            return_value=[entry],
        ),
        patch(
            "app.services.tools._executor_persona_history._build_search_matches",
            return_value=([match], 1),
        ),
    ):
        result = await search_persona_history("topic:task-123", project_id="agent-hub")

    assert "Persona history matches (1/1)" in result
    assert "topic=task:task-123" in result
    assert 'inspect_session(session_id="sess-1")' in result


@pytest.mark.asyncio
async def test_search_persona_history_requires_query() -> None:
    result = await search_persona_history("")

    assert result == "Error: query is required"
