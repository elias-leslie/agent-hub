"""Tests for completion request setup memory injection behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.api.complete.orchestration_helpers import build_session_and_messages
from app.api.complete.request_schemas import SourceMetadata, WorkContext
from app.api.complete.request_setup import inject_memory, setup_session
from app.api.complete.work_context import inject_work_context_message, work_context_to_prompt


class _FakeContext:
    def __init__(self) -> None:
        self.mandates = ["m1"]
        self.guardrails = ["g1"]
        self.reference = ["r1"]
        self.debug_info = {
            "reference_selected_uuids": ["ref-selected-1"],
            "reference_index_uuids": [],
        }

    def get_loaded_uuids(self) -> list[str]:
        return ["11111111-1111-1111-1111-111111111111"]


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        use_memory=True,
        memory_group_id="project:agent-hub",
        memory_variant_override=None,
        task_type=None,
        phase=None,
        project_id="agent-hub",
        external_id=None,
        trace_id=None,
        parent_session_id=None,
        current_branch=None,
        working_dir=None,
        source_metadata=None,
        work_context=None,
        session_id=None,
        agent_slug="coder",
        max_turns=1,
        execute_tools=False,
        temperature=1.0,
        messages=[SimpleNamespace(role="user", content="hi")],
    )


def _resolved_agent(memory_config: dict[str, object] | None) -> SimpleNamespace:
    return SimpleNamespace(agent=SimpleNamespace(memory_config=memory_config, slug="coder"))


def test_work_context_prompt_injects_project_task_context() -> None:
    context = WorkContext(
        mode="project_task",
        project_id="summitflow",
        project_name="SummitFlow",
        task_id="task-123",
        task_title="Build Work Chats",
        pane_id="pane-1",
        surface="work_chats",
    )

    prompt = work_context_to_prompt(context)
    messages = inject_work_context_message([], context)

    assert prompt is not None
    assert "project: summitflow" in prompt
    assert "task: task-123" in prompt
    assert "pane: pane-1" in prompt
    assert messages[0].role == "system"
    assert messages[0].content == prompt


@pytest.mark.asyncio
async def test_inject_memory_skips_when_injection_disabled_flag() -> None:
    request = _request()
    messages = [{"role": "user", "content": "hi"}]

    with patch(
        "app.api.complete.request_setup.inject_progressive_context",
        new_callable=AsyncMock,
    ) as mock_inject:
        result_messages, injected_count, loaded = await inject_memory(
            request=request,
            messages_dict=messages,
            session_id="s1",
            resolved_agent=_resolved_agent({"injection_enabled": False}),
            db=None,
        )

    assert result_messages == messages
    assert injected_count == 0
    assert loaded == []
    mock_inject.assert_not_awaited()


@pytest.mark.asyncio
async def test_inject_memory_skips_when_enabled_false() -> None:
    request = _request()

    with patch(
        "app.api.complete.request_setup.inject_progressive_context",
        new_callable=AsyncMock,
    ) as mock_inject:
        _, injected_count, loaded = await inject_memory(
            request=request,
            messages_dict=[{"role": "user", "content": "hi"}],
            session_id="s1",
            resolved_agent=_resolved_agent({"enabled": False}),
            db=None,
        )

    assert injected_count == 0
    assert loaded == []
    mock_inject.assert_not_awaited()


@pytest.mark.asyncio
async def test_inject_memory_requires_both_enabled_and_injection_enabled() -> None:
    request = _request()

    with patch(
        "app.api.complete.request_setup.inject_progressive_context",
        new_callable=AsyncMock,
    ) as mock_inject:
        _, injected_count, loaded = await inject_memory(
            request=request,
            messages_dict=[{"role": "user", "content": "hi"}],
            session_id="s1",
            resolved_agent=_resolved_agent({"enabled": False, "injection_enabled": True}),
            db=None,
        )

    assert injected_count == 0
    assert loaded == []
    mock_inject.assert_not_awaited()


@pytest.mark.asyncio
async def test_inject_memory_tracks_loaded_batch_when_enabled() -> None:
    request = _request()
    request.memory_variant_override = "MINIMAL"
    db = AsyncMock()

    with (
        patch(
            "app.api.complete.request_setup.parse_memory_group_id",
            return_value=("project", "agent-hub"),
        ),
        patch(
            "app.api.complete.request_setup.inject_progressive_context",
            new_callable=AsyncMock,
            return_value=([{"role": "system", "content": "mem"}], _FakeContext()),
        ) as mock_inject,
        patch(
            "app.api.complete.request_setup.track_loaded_batch",
            new_callable=AsyncMock,
        ) as mock_track,
        patch(
            "app.api.complete.request_setup.store_memory_inject_event",
            new_callable=AsyncMock,
        ) as mock_store,
    ):
        result_messages, injected_count, loaded = await inject_memory(
            request=request,
            messages_dict=[{"role": "user", "content": "hi"}],
            session_id="s1",
            resolved_agent=_resolved_agent({"include_mandates": True}),
            db=db,
        )

    assert result_messages[0]["role"] == "system"
    assert injected_count == 3
    assert loaded == ["11111111-1111-1111-1111-111111111111"]
    mock_inject.assert_awaited_once()
    inject_args = mock_inject.await_args
    assert inject_args is not None
    assert inject_args.kwargs["variant"] == "MINIMAL"
    assert inject_args.kwargs["consumer_profile"] is None
    mock_track.assert_awaited_once_with(["11111111-1111-1111-1111-111111111111"])
    mock_store.assert_awaited_once()
    store_args = mock_store.await_args
    assert store_args is not None
    assert store_args.kwargs["reference_selected_uuids"] == ["ref-selected-1"]
    assert store_args.kwargs["reference_index_uuids"] == []
    assert store_args.kwargs["memory_debug"] == {
        "reference_selected_uuids": ["ref-selected-1"],
        "reference_index_uuids": [],
    }


@pytest.mark.asyncio
async def test_inject_memory_forwards_runtime_consumer_profile_from_agent_config() -> None:
    request = _request()

    with patch(
        "app.api.complete.request_setup.inject_progressive_context",
        new_callable=AsyncMock,
        return_value=([{"role": "system", "content": "mem"}], _FakeContext()),
    ) as mock_inject:
        await inject_memory(
            request=request,
            messages_dict=[{"role": "user", "content": "hi"}],
            session_id="s1",
            resolved_agent=_resolved_agent({"runtime_consumer_profile": "agent_coding"}),
            db=None,
        )

    assert mock_inject.await_args is not None
    assert mock_inject.await_args.kwargs["consumer_profile"] == "agent_coding"


@pytest.mark.asyncio
async def test_build_session_and_messages_records_reference_breakdown_on_non_streaming_path() -> None:
    request = _request()
    db = AsyncMock()
    session = SimpleNamespace(id="sess-123")

    with (
        patch(
            "app.api.complete.orchestration_helpers.setup_session",
            new_callable=AsyncMock,
            return_value=("sess-123", session, [], True),
        ),
        patch(
            "app.api.complete.orchestration_helpers.inject_agent_system_prompt",
            side_effect=lambda messages, _mandate: messages,
        ),
        patch(
            "app.api.complete.request_setup.parse_memory_group_id",
            return_value=("project", "agent-hub"),
        ),
        patch(
            "app.api.complete.request_setup.inject_progressive_context",
            new_callable=AsyncMock,
            return_value=([{"role": "system", "content": "mem"}], _FakeContext()),
        ),
        patch(
            "app.api.complete.request_setup.track_loaded_batch",
            new_callable=AsyncMock,
        ),
        patch(
            "app.api.complete.request_setup.store_memory_inject_event",
            new_callable=AsyncMock,
        ) as mock_store,
        patch(
            "app.api.complete.orchestration_helpers.check_context_limits",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.api.complete.orchestration_helpers.check_cache",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        result = await build_session_and_messages(
            request=request,
            provider="claude",
            resolved_model="claude-sonnet-4-6",
            resolved_agent=_resolved_agent({"include_mandates": True}),
            mandate=None,
            db=db,
            client_id="client-1",
            source="pytest",
            skip_cache=True,
        )

    assert result[0] is False
    assert result[1] == "sess-123"
    assert result[6] == 3
    assert result[7] == ["11111111-1111-1111-1111-111111111111"]
    store_args = mock_store.await_args
    assert store_args is not None
    assert store_args.kwargs["reference_selected_uuids"] == ["ref-selected-1"]
    assert store_args.kwargs["reference_index_uuids"] == []
    assert store_args.kwargs["memory_debug"] == {
        "reference_selected_uuids": ["ref-selected-1"],
        "reference_index_uuids": [],
    }


@pytest.mark.asyncio
async def test_setup_session_forwards_working_dir_to_session_creation() -> None:
    request = _request()
    request.project_id = "summitflow"
    request.current_branch = "task-123/main"
    request.working_dir = "/tmp/lanes/task-123"
    request.parent_session_id = "persona-root"

    session = SimpleNamespace(id="sess-1")
    with patch(
        "app.api.complete.request_setup.get_or_create_session",
        new_callable=AsyncMock,
        return_value=(session, [], True),
    ) as mock_get_or_create, patch(
        "app.api.complete.request_setup.publish_session_start",
        new_callable=AsyncMock,
    ) as mock_publish:
        session_id, returned_session, context_messages, is_new_session = await setup_session(
            request=request,
            provider="claude",
            resolved_model="claude-sonnet-4-6",
            db=AsyncMock(),
            client_id="client-1",
            request_source="test",
        )

    assert session_id == "sess-1"
    assert returned_session is session
    assert context_messages == []
    assert is_new_session is True
    mock_get_or_create.assert_awaited_once()
    get_args = mock_get_or_create.await_args
    assert get_args is not None
    assert get_args.kwargs["working_dir"] == "/tmp/lanes/task-123"
    assert get_args.kwargs["current_branch"] == "task-123/main"
    assert get_args.kwargs["parent_session_id"] == "persona-root"
    mock_publish.assert_awaited_once_with("sess-1", "claude-sonnet-4-6", "summitflow")


@pytest.mark.asyncio
async def test_setup_session_forwards_trace_id_to_session_creation() -> None:
    request = _request()
    request.project_id = "vantage"
    request.trace_id = "vantage:issue:iss-123:run:run-456"

    session = SimpleNamespace(id="sess-1")
    with patch(
        "app.api.complete.request_setup.get_or_create_session",
        new_callable=AsyncMock,
        return_value=(session, [], False),
    ) as mock_get_or_create:
        session_id, returned_session, context_messages, is_new_session = await setup_session(
            request=request,
            provider="claude",
            resolved_model="claude-sonnet-4-6",
            db=AsyncMock(),
            client_id="client-1",
            request_source="vantage",
        )

    assert session_id == "sess-1"
    assert returned_session is session
    assert context_messages == []
    assert is_new_session is False
    get_args = mock_get_or_create.await_args
    assert get_args is not None
    assert get_args.kwargs["trace_id"] == "vantage:issue:iss-123:run:run-456"


@pytest.mark.asyncio
async def test_setup_session_binds_work_context_and_source_metadata() -> None:
    request = _request()
    request.work_context = WorkContext(
        project_id="summitflow",
        task_id="task-123",
        pane_id="pane-1",
        surface="work_chats",
    )
    request.source_metadata = SourceMetadata(
        transport="web",
        surface="work_chats",
        pane_id="pane-1",
        source_client="agent-hub/work-chats",
    )

    session = SimpleNamespace(id="sess-1")
    with (
        patch(
            "app.api.complete.request_setup.get_or_create_session",
            new_callable=AsyncMock,
            return_value=(session, [], True),
        ),
        patch(
            "app.api.complete.request_setup.bind_request_context",
            new_callable=AsyncMock,
        ) as mock_bind,
        patch(
            "app.api.complete.request_setup.publish_session_start",
            new_callable=AsyncMock,
        ),
    ):
        await setup_session(
            request=request,
            provider="claude",
            resolved_model="claude-sonnet-4-6",
            db=AsyncMock(),
            client_id="client-1",
            request_source="test",
        )

    mock_bind.assert_awaited_once()
    bind_args = mock_bind.await_args
    assert bind_args is not None
    assert bind_args.kwargs["session"] is session
    assert bind_args.kwargs["work_context"] is request.work_context
    assert bind_args.kwargs["source_metadata"] is request.source_metadata
