from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import SessionBinding, SessionEventType
from app.services.event_storage import store_child_session_lifecycle_event
from app.services.session_bindings import (
    apply_work_chat_metadata,
    bind_request_context,
    upsert_session_binding,
)


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

    with (
        patch("app.services.event_storage.get_max_turn", new_callable=AsyncMock) as max_turn,
        patch(
            "app.services.event_storage.get_max_sequence", new_callable=AsyncMock
        ) as max_sequence,
        patch("app.services.event_storage.store_event", new_callable=AsyncMock) as mock_store,
    ):
        max_turn.return_value = 19
        max_sequence.return_value = 2603
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
    assert kwargs["turn"] == 19
    assert kwargs["sequence"] == 2604
    assert kwargs["pane_id"] == "pane-1"
    assert kwargs["surface"] == "work_chats"
    assert kwargs["source_client"] == "agent-hub/work-chats"
    assert kwargs["tool_output"]["child_session_id"] == "child-session"
    assert kwargs["tool_output"]["observed_write_paths"] == [
        "frontend/src/app/work-chats/page.tsx"
    ]


def _db_with_existing(binding: SessionBinding | None) -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = binding
    db.execute = AsyncMock(return_value=result)
    return db


def test_apply_work_chat_metadata_merges_context_and_source_keys() -> None:
    session = SimpleNamespace(provider_metadata={"existing": True})

    apply_work_chat_metadata(
        session,
        work_context={"project_id": "design-tools", "design_id": "d-1"},
        source_metadata={"surface": "st.design.asset.critique", "source_client": "design-tools", "pane_id": ""},
    )

    assert session.provider_metadata == {
        "existing": True,
        "work_context": {"project_id": "design-tools", "design_id": "d-1"},
        "source_metadata": {
            "surface": "st.design.asset.critique",
            "source_client": "design-tools",
            "pane_id": "",
        },
        "surface": "st.design.asset.critique",
        "source_client": "design-tools",
    }


def test_apply_work_chat_metadata_noop_without_metadata() -> None:
    session = SimpleNamespace(provider_metadata=None)
    apply_work_chat_metadata(session, work_context=None, source_metadata={})
    assert session.provider_metadata is None


@pytest.mark.asyncio
async def test_upsert_session_binding_creates_new_row() -> None:
    db = _db_with_existing(None)

    binding = await upsert_session_binding(
        db,
        session_id="session-1",
        surface="st.design.asset.critique",
        project_id="design-tools",
        design_id="d-1",
        work_context={"design_id": "d-1"},
    )

    db.add.assert_called_once_with(binding)
    db.flush.assert_awaited_once()
    assert binding.session_id == "session-1"
    assert binding.surface == "st.design.asset.critique"
    assert binding.design_id == "d-1"
    assert binding.work_context == {"design_id": "d-1"}


@pytest.mark.asyncio
async def test_upsert_session_binding_updates_existing_pane_row() -> None:
    existing = SessionBinding(surface="work_chats", pane_id="pane-1", session_id="old-session")
    db = _db_with_existing(existing)

    binding = await upsert_session_binding(
        db,
        session_id="new-session",
        pane_id="pane-1",
        task_id="task-9",
    )

    assert binding is existing
    db.add.assert_not_called()
    assert binding.session_id == "new-session"
    assert binding.task_id == "task-9"
    assert binding.work_context == {}


@pytest.mark.asyncio
async def test_bind_request_context_writes_binding_from_source_metadata() -> None:
    session = SimpleNamespace(
        id="session-1", project_id="design-tools", external_id="ext-1", provider_metadata={}
    )
    db = AsyncMock()

    with patch(
        "app.services.session_bindings.upsert_session_binding", new_callable=AsyncMock
    ) as mock_upsert:
        await bind_request_context(
            db,
            session=session,
            work_context={"design_id": "d-1"},
            source_metadata={"surface": "st.design.asset.critique", "source_client": "design-tools"},
        )

    mock_upsert.assert_awaited_once()
    assert mock_upsert.await_args is not None
    kwargs = mock_upsert.await_args.kwargs
    assert kwargs["session_id"] == "session-1"
    assert kwargs["surface"] == "st.design.asset.critique"
    assert kwargs["pane_id"] is None
    assert kwargs["project_id"] == "design-tools"
    assert kwargs["task_id"] == "ext-1"
    assert kwargs["design_id"] == "d-1"
    assert kwargs["source_client"] == "design-tools"
    assert session.provider_metadata["work_context"] == {"design_id": "d-1"}


@pytest.mark.asyncio
async def test_bind_request_context_skips_without_metadata() -> None:
    session = SimpleNamespace(id="session-1", project_id=None, external_id=None, provider_metadata={})
    with patch(
        "app.services.session_bindings.upsert_session_binding", new_callable=AsyncMock
    ) as mock_upsert:
        await bind_request_context(AsyncMock(), session=session, work_context=None, source_metadata=None)
    mock_upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_bind_request_context_design_tools_write_creates_and_updates_binding() -> None:
    session = SimpleNamespace(
        id="session-1", project_id="design-tools", external_id=None, provider_metadata={}
    )
    source = {
        "surface": "st.design.asset.critique",
        "source_client": "design-tools",
        "transport": "cli",
        "chat_id": "chat-1",
        "message_id": "msg-1",
    }
    db = _db_with_existing(None)

    await bind_request_context(
        db, session=session, work_context={"design_id": "d-1"}, source_metadata=source
    )

    db.add.assert_called_once()
    created = db.add.call_args.args[0]
    assert isinstance(created, SessionBinding)
    assert created.surface == "st.design.asset.critique"
    assert created.session_id == "session-1"
    assert created.design_id == "d-1"
    assert created.source_client == "design-tools"
    lookup_sql = str(db.execute.await_args.args[0])
    assert "chat_id" not in lookup_sql
    assert "session_bindings.design_id" in lookup_sql

    db = _db_with_existing(created)
    session.id = "session-2"
    await bind_request_context(
        db, session=session, work_context={"design_id": "d-1"}, source_metadata=source
    )
    db.add.assert_not_called()
    assert created.session_id == "session-2"
