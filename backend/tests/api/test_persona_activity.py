from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.persona.activity import get_activity
from app.models.session import Session


@pytest.mark.asyncio
async def test_get_activity_exposes_count_and_status_provenance() -> None:
    session = Session(
        id="sess-1",
        project_id="agent-hub",
        provider="codex",
        model="codex/gpt-5.4",
        status="active",
        agent_slug="persona",
        session_type="agent",
        provider_metadata={
            "live_activity": {"phase": "error", "status": "error", "summary": "Tool failed"},
        },
    )
    session.created_at = datetime.now(UTC)
    session.updated_at = datetime.now(UTC)

    child = Session(
        id="child-1",
        project_id="agent-hub",
        provider="codex",
        model="codex/gpt-5.4",
        status="active",
        agent_slug="coder",
        session_type="agent",
        parent_session_id="sess-1",
        provider_metadata={
            "live_activity": {"phase": "running_tool", "status": "active", "summary": "Working"},
        },
    )
    child.created_at = datetime.now(UTC)
    child.updated_at = datetime.now(UTC)

    count_result = MagicMock()
    count_result.scalar.return_value = 1

    sessions_result = MagicMock()
    sessions_result.scalars.return_value.all.return_value = [session]

    previews_result = MagicMock()
    previews_result.all.return_value = []

    msg_counts_result = MagicMock()
    msg_counts_result.all.return_value = [MagicMock(session_id="sess-1", cnt=2)]

    event_counts_result = MagicMock()
    event_counts_result.all.return_value = [MagicMock(session_id="sess-1", cnt=5)]

    child_result = MagicMock()
    child_result.scalars.return_value.all.return_value = [child]

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[count_result, sessions_result, previews_result, msg_counts_result, event_counts_result, child_result])

    response = await get_activity(db=db, time_range="24h", page=1, page_size=50)

    assert response.total == 1
    assert response.sessions[0].message_count == 2
    assert response.sessions[0].event_count == 5
    assert response.sessions[0].child_session_count == 1
    assert response.sessions[0].active_child_session_count == 1
    assert response.sessions[0].status_source == "runtime"
    assert response.sessions[0].status_matches_live is False
    assert response.sessions[0].live_status == "error"
    assert response.sessions[0].live_source == "runtime"
