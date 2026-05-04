from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.models import SessionEventType
from app.services.event_storage import store_child_session_lifecycle_event


@pytest.mark.asyncio
async def test_child_session_lifecycle_event_is_stored_on_parent_with_source_metadata() -> None:
    child = SimpleNamespace(
        id="child-session",
        parent_session_id="parent-session",
        status="active",
        agent_slug="coder",
        project_id="summitflow",
        external_id="task-123",
        summary_oneliner="editing files",
        workstream_status=None,
        current_branch="task-123/main",
        observed_write_paths=["frontend/src/app/work-chats/page.tsx"],
        provider_metadata={
            "source_metadata": {
                "transport": "web",
                "surface": "work_chats",
                "pane_id": "pane-1",
                "source_client": "agent-hub/work-chats",
            }
        },
    )

    with patch("app.services.event_storage.store_event", new_callable=AsyncMock) as mock_store:
        await store_child_session_lifecycle_event(
            AsyncMock(),
            child,
            SessionEventType.CHILD_SESSION_STARTED,
        )

    mock_store.assert_awaited_once()
    store_args = mock_store.await_args
    assert store_args is not None
    kwargs = store_args.kwargs
    assert kwargs["session_id"] == "parent-session"
    assert kwargs["event_type"] == SessionEventType.CHILD_SESSION_STARTED
    assert kwargs["pane_id"] == "pane-1"
    assert kwargs["surface"] == "work_chats"
    assert kwargs["source_client"] == "agent-hub/work-chats"
    assert kwargs["tool_output"]["child_session_id"] == "child-session"
    assert kwargs["tool_output"]["observed_write_paths"] == [
        "frontend/src/app/work-chats/page.tsx"
    ]
