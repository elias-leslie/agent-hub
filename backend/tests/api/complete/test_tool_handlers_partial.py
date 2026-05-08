"""Tests for tool_handlers partial response storage on error paths."""

from __future__ import annotations

import asyncio
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.runtime_session import StreamBackedRuntimeSession
from app.api.complete.tool_handler_utils import (
    _ExecutionState,
    _init_execution_state,
    _run_tool_loop,
)
from app.api.complete.tool_handlers import _store_partial_response
from app.constants.models import CLAUDE_SONNET


def _mock_session() -> MagicMock:
    """Create a mock DBSession with a mutable status attribute."""
    session = MagicMock()
    session.status = "active"
    return session


def _mock_adapter_with_stream(stream: object) -> MagicMock:
    adapter = MagicMock()
    adapter.start_tool_session = AsyncMock(
        return_value=StreamBackedRuntimeSession(stream=stream),
    )
    return adapter


def test_init_execution_state_marks_task_sessions_for_progress_tags() -> None:
    session = MagicMock(agent_slug="coder", external_id="task-1234")

    state = _init_execution_state(
        session,
        messages=[{"role": "user", "content": "Inspect the tool loop."}],
    )

    assert state.agent_slug == "coder"
    assert state.external_id == "task-1234"
    assert state.requires_progress_tags is True


class TestStorePartialResponse:
    """Verify _store_partial_response stores accumulated content on error."""

    @pytest.mark.asyncio
    async def test_stores_accumulated_content(self):
        """Partial content should be stored even when tool loop fails."""
        state = _ExecutionState(
            agent_slug="persona",
            messages_for_adapter=[],
            content_parts=["Hello, ", "I found an issue with..."],
            thinking_parts=["Let me check the logs"],
        )
        mock_db = AsyncMock()
        session = _mock_session()

        with patch(
            "app.api.complete.tool_handlers.store_assistant_response",
            new_callable=AsyncMock,
        ) as mock_store:
            await _store_partial_response(mock_db, "session-123", session, state, CLAUDE_SONNET)

            # Rollback called before storage to clear dirty transaction state
            mock_db.rollback.assert_called_once()
            mock_store.assert_called_once()
            call_kwargs = mock_store.call_args
            # Content should be joined
            assert call_kwargs[0][2] == "Hello, I found an issue with..."
            # Model passed through
            assert call_kwargs[0][3] == CLAUDE_SONNET
            # Session marked as completed
            assert session.status == "completed"
            # db.commit() called after storage
            mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_stores_fallback_content_on_early_error(self):
        """With no accumulated content, a fallback message should be stored."""
        state = _ExecutionState(
            agent_slug="persona",
            messages_for_adapter=[],
            content_parts=[],
            thinking_parts=[],
        )
        mock_db = AsyncMock()
        session = _mock_session()

        with patch(
            "app.api.complete.tool_handlers.store_assistant_response",
            new_callable=AsyncMock,
        ) as mock_store:
            await _store_partial_response(mock_db, "session-456", session, state, CLAUDE_SONNET)

            mock_db.rollback.assert_called_once()
            mock_store.assert_called_once()
            assert mock_store.call_args[0][2] == "Session interrupted before response"
            assert session.status == "completed"

    @pytest.mark.asyncio
    async def test_suppresses_storage_errors(self):
        """Storage failure should not raise — it's a best-effort operation."""
        state = _ExecutionState(
            agent_slug="persona",
            messages_for_adapter=[],
            content_parts=["partial"],
        )
        mock_db = AsyncMock()
        session = _mock_session()

        with patch(
            "app.api.complete.tool_handlers.store_assistant_response",
            new_callable=AsyncMock,
            side_effect=Exception("DB connection lost"),
        ):
            # Should not raise
            await _store_partial_response(mock_db, "session-789", session, state, CLAUDE_SONNET)


@pytest.mark.asyncio
async def test_run_tool_loop_drains_stream_after_terminal_error() -> None:
    """Terminal error events should not abort the provider stream mid-iteration."""
    state = _ExecutionState(agent_slug="persona", messages_for_adapter=[])
    tracker = AsyncMock()
    db = AsyncMock()
    stream_state = {"natural_end": False, "closed_early": False}

    class FakeEventStream:
        def __init__(self) -> None:
            self.closed = False

        def __aiter__(self):
            return self._iter()

        async def _iter(self):
            try:
                yield types.SimpleNamespace(type="error", error="claude tool failed"), None
                yield types.SimpleNamespace(type="result", result="ignored"), None
                stream_state["natural_end"] = True
            finally:
                if not stream_state["natural_end"]:
                    stream_state["closed_early"] = True

        async def aclose(self) -> None:
            self.closed = True

    fake_stream = FakeEventStream()
    adapter = _mock_adapter_with_stream(fake_stream)

    result = await _run_tool_loop(
        adapter=adapter,
        state=state,
        provider="claude",
        model="claude-sonnet-4-6",
        tools=[],
        tool_catalog=None,
        working_dir=None,
        session_id="session-123",
        loaded_memory_uuids=[],
        db=db,
        tracker=tracker,
        max_turns=1,
        project_id="persona-sandbox",
    )

    assert result is not None
    assert result.status == "error"
    assert result.error == "claude tool failed"
    assert stream_state["natural_end"] is True
    assert stream_state["closed_early"] is False
    assert fake_stream.closed is False


@pytest.mark.asyncio
async def test_run_tool_loop_does_not_reclose_exhausted_stream() -> None:
    state = _ExecutionState(agent_slug="persona", messages_for_adapter=[])
    tracker = AsyncMock()
    db = AsyncMock()

    class FakeEventStream:
        def __init__(self) -> None:
            self.aclose_calls = 0

        def __aiter__(self):
            return self._iter()

        async def _iter(self):
            yield types.SimpleNamespace(type="result", result="done", finish_reason="end_turn"), None

        async def aclose(self) -> None:
            self.aclose_calls += 1

    fake_stream = FakeEventStream()
    adapter = _mock_adapter_with_stream(fake_stream)

    result = await _run_tool_loop(
        adapter=adapter,
        state=state,
        provider="claude",
        model="claude-sonnet-4-6",
        tools=[],
        tool_catalog=None,
        working_dir=None,
        session_id="session-789",
        loaded_memory_uuids=[],
        db=db,
        tracker=tracker,
        max_turns=1,
        project_id="agent-hub",
    )

    assert result is None
    assert fake_stream.aclose_calls == 0


@pytest.mark.asyncio
async def test_run_tool_loop_interrupts_owned_runtime_session_on_cancellation() -> None:
    state = _ExecutionState(agent_slug="persona", messages_for_adapter=[])
    tracker = AsyncMock()
    db = AsyncMock()
    interrupt = AsyncMock()
    close = AsyncMock()

    async def fake_stream():
        raise asyncio.CancelledError()
        yield

    adapter = MagicMock()
    adapter.start_tool_session = AsyncMock(return_value=StreamBackedRuntimeSession(
        stream=fake_stream(),
        interrupt_callback=interrupt,
        close_callback=close,
    ))

    with pytest.raises(asyncio.CancelledError):
        await _run_tool_loop(
            adapter=adapter,
            state=state,
            provider="claude",
            model="claude-sonnet-4-6",
            tools=[],
            tool_catalog=None,
            working_dir=None,
            session_id="session-cancelled",
            loaded_memory_uuids=[],
            db=db,
            tracker=tracker,
            max_turns=1,
            project_id="agent-hub",
        )

    interrupt.assert_awaited_once()
    close.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_tool_loop_floors_codex_tool_turns_before_adapter_call() -> None:
    state = _ExecutionState(agent_slug="memory-curator", messages_for_adapter=[])
    tracker = AsyncMock()
    db = AsyncMock()

    async def fake_stream():
        yield types.SimpleNamespace(type="result", result="done", finish_reason="end_turn"), None

    adapter = _mock_adapter_with_stream(fake_stream())

    result = await _run_tool_loop(
        adapter=adapter,
        state=state,
        provider="codex",
        model="codex/gpt-5.4",
        tools=[],
        tool_catalog=None,
        working_dir=None,
        session_id="sess-1",
        loaded_memory_uuids=[],
        db=db,
        tracker=tracker,
        max_turns=1,
        project_id="agent-hub",
    )

    assert result is None
    assert adapter.start_tool_session.call_args.kwargs["max_turns"] == 3


@pytest.mark.asyncio
async def test_run_tool_loop_preserves_claude_tool_turns_before_adapter_call() -> None:
    state = _ExecutionState(agent_slug="debugger", messages_for_adapter=[])
    tracker = AsyncMock()
    db = AsyncMock()

    async def fake_stream():
        yield types.SimpleNamespace(type="result", result="done", finish_reason="end_turn"), None

    adapter = _mock_adapter_with_stream(fake_stream())

    result = await _run_tool_loop(
        adapter=adapter,
        state=state,
        provider="claude",
        model="claude-sonnet-4-6",
        tools=[],
        tool_catalog=None,
        working_dir=None,
        session_id="sess-2",
        loaded_memory_uuids=[],
        db=db,
        tracker=tracker,
        max_turns=7,
        project_id="agent-hub",
    )

    assert result is None
    assert adapter.start_tool_session.call_args.kwargs["max_turns"] == 7


@pytest.mark.asyncio
async def test_run_tool_loop_tracks_tool_result_summaries() -> None:
    state = _ExecutionState(agent_slug="refactor", messages_for_adapter=[])
    tracker = AsyncMock()
    db = AsyncMock()

    class FakeEventStream:
        def __aiter__(self):
            return self._iter()

        async def _iter(self):
            yield types.SimpleNamespace(
                type="assistant",
                message=types.SimpleNamespace(
                    content=[
                        types.SimpleNamespace(
                            type="tool_use",
                            name="Bash",
                            input={"command": "st pulse"},
                            id="tool-1",
                        )
                    ]
                ),
            ), None
            yield types.SimpleNamespace(
                type="tool_result",
                tool_use_id="tool-1",
                content="PULSE:agent-hub|tasks=0",
                is_error=False,
                duration_ms=5,
            ), None
            yield types.SimpleNamespace(type="result", result="Mode: campaign"), None

        async def aclose(self) -> None:
            return None

    adapter = _mock_adapter_with_stream(FakeEventStream())

    with (
        patch(
            "app.api.complete.tool_event_storage.store_tool_use",
            new_callable=AsyncMock,
        ),
        patch(
            "app.api.complete.tool_event_storage.store_tool_result",
            new_callable=AsyncMock,
        ),
    ):
        result = await _run_tool_loop(
            adapter=adapter,
            state=state,
            provider="claude",
            model="claude-sonnet-4-6",
            tools=[],
            tool_catalog=None,
            working_dir=None,
            session_id="session-456",
            loaded_memory_uuids=[],
            db=db,
            tracker=tracker,
            max_turns=1,
            project_id="agent-hub",
        )

    assert result is None
    assert state.tool_result_summaries == ["Bash: PULSE:agent-hub|tasks=0"]
    assert state.terminal_finish_reason == "end_turn"
    assert state.turn == 2


@pytest.mark.asyncio
async def test_run_tool_loop_stops_repeated_identical_tool_results() -> None:
    state = _ExecutionState(agent_slug="debugger", messages_for_adapter=[])
    tracker = AsyncMock()
    db = AsyncMock()

    class FakeEventStream:
        def __aiter__(self):
            return self._iter()

        async def _iter(self):
            for index in range(6):
                tool_id = f"tool-{index}"
                yield types.SimpleNamespace(
                    type="assistant",
                    message=types.SimpleNamespace(
                        content=[
                            types.SimpleNamespace(
                                type="tool_use",
                                name="bash",
                                input={"command": "python probe.py"},
                                id=tool_id,
                            )
                        ]
                    ),
                ), None
                yield types.SimpleNamespace(
                    type="tool_result",
                    tool_use_id=tool_id,
                    content="same probe output",
                    is_error=False,
                    duration_ms=5,
                ), None

        async def aclose(self) -> None:
            return None

    adapter = _mock_adapter_with_stream(FakeEventStream())

    with (
        patch(
            "app.api.complete.tool_event_storage.store_tool_use",
            new_callable=AsyncMock,
        ),
        patch(
            "app.api.complete.tool_event_storage.store_tool_result",
            new_callable=AsyncMock,
        ),
    ):
        result = await _run_tool_loop(
            adapter=adapter,
            state=state,
            provider="kimi-code",
            model="kimi-code/kimi-for-coding",
            tools=[],
            tool_catalog=None,
            working_dir=None,
            session_id="session-repeat",
            loaded_memory_uuids=[],
            db=db,
            tracker=tracker,
            max_turns=50,
            project_id="agent-hub",
        )

    assert result is not None
    assert result.status == "error"
    assert "Repeated identical tool result 5 times for bash" in (result.error or "")
    assert state.tool_calls_count == 5


@pytest.mark.asyncio
async def test_run_tool_loop_short_circuits_after_detached_agent_hub_rebuild_queue() -> None:
    state = _ExecutionState(agent_slug="persona", messages_for_adapter=[])
    tracker = AsyncMock()
    db = AsyncMock()

    class FakeEventStream:
        def __init__(self) -> None:
            self.aclose_calls = 0
            self.resumed_after_tool_result = False

        def __aiter__(self):
            return self._iter()

        async def _iter(self):
            yield types.SimpleNamespace(
                type="assistant",
                message=types.SimpleNamespace(
                    content=[
                        types.SimpleNamespace(
                            type="tool_use",
                            name="bash",
                            input={"command": "cd /srv/workspaces/projects/agent-hub && rebuild.sh --detach agent-hub"},
                            id="tool-1",
                        )
                    ]
                ),
            ), None
            yield types.SimpleNamespace(
                type="tool_result",
                tool_use_id="tool-1",
                content="[18:23:59] Queueing detached rebuild for agent-hub...\nDetached rebuild queued: sf-rebuild-agent-hub.service\nRunning as unit: sf-rebuild-agent-hub.service",
                is_error=False,
                duration_ms=5,
            ), None
            self.resumed_after_tool_result = True
            yield types.SimpleNamespace(type="result", result="should not run", finish_reason="end_turn"), None

        async def aclose(self) -> None:
            self.aclose_calls += 1

    fake_stream = FakeEventStream()
    adapter = _mock_adapter_with_stream(fake_stream)

    with (
        patch(
            "app.api.complete.tool_event_storage.store_tool_use",
            new_callable=AsyncMock,
        ),
        patch(
            "app.api.complete.tool_event_storage.store_tool_result",
            new_callable=AsyncMock,
        ),
    ):
        result = await _run_tool_loop(
            adapter=adapter,
            state=state,
            provider="codex",
            model="codex/gpt-5.4",
            tools=[],
            tool_catalog=None,
            working_dir="/srv/workspaces/projects/agent-hub",
            session_id="session-detached-rebuild",
            loaded_memory_uuids=[],
            db=db,
            tracker=tracker,
            max_turns=20,
            project_id="agent-hub",
        )

    assert result is None
    assert fake_stream.aclose_calls == 1
    assert fake_stream.resumed_after_tool_result is False
    assert state.terminal_finish_reason == "end_turn"
    assert state.turn == 1
    assert state.content_parts == [
        "HEARTBEAT_ACTION — Detached Agent Hub rebuild queued as sf-rebuild-agent-hub.service. "
        "Post-restart verification is deferred to a fresh session.\n"
        "[[P:started:ending the heartbeat after queueing a detached Agent Hub rebuild]]\n"
        "[[P:decision:queued detached Agent Hub rebuild as sf-rebuild-agent-hub.service "
        "and ended before post-restart verification]]\n"
        "[[S:partial:Queued detached Agent Hub rebuild; a fresh post-restart session "
        "must verify health and task completion.]]"
    ]


@pytest.mark.asyncio
async def test_run_tool_loop_formats_detached_rebuild_closeout_for_task_session() -> None:
    state = _ExecutionState(
        agent_slug="coder",
        messages_for_adapter=[],
        external_id="task-12345678",
    )
    tracker = AsyncMock()
    db = AsyncMock()

    class FakeEventStream:
        def __aiter__(self):
            return self._iter()

        async def _iter(self):
            yield types.SimpleNamespace(
                type="assistant",
                message=types.SimpleNamespace(
                    content=[
                        types.SimpleNamespace(
                            type="tool_use",
                            name="bash",
                            input={"command": "cd /srv/workspaces/projects/agent-hub && rebuild.sh --detach agent-hub"},
                            id="tool-1",
                        )
                    ]
                ),
            ), None
            yield types.SimpleNamespace(
                type="tool_result",
                tool_use_id="tool-1",
                content="Detached rebuild queued: sf-rebuild-agent-hub.service\nRunning as unit: sf-rebuild-agent-hub.service",
                is_error=False,
                duration_ms=5,
            ), None

        async def aclose(self) -> None:
            return None

    adapter = _mock_adapter_with_stream(FakeEventStream())

    with (
        patch(
            "app.api.complete.tool_event_storage.store_tool_use",
            new_callable=AsyncMock,
        ),
        patch(
            "app.api.complete.tool_event_storage.store_tool_result",
            new_callable=AsyncMock,
        ),
    ):
        result = await _run_tool_loop(
            adapter=adapter,
            state=state,
            provider="codex",
            model="codex/gpt-5.4",
            tools=[],
            tool_catalog=None,
            working_dir="/srv/workspaces/projects/agent-hub",
            session_id="session-detached-rebuild-task",
            loaded_memory_uuids=[],
            db=db,
            tracker=tracker,
            max_turns=20,
            project_id="agent-hub",
        )

    assert result is None
    assert state.content_parts == [
        "Detached Agent Hub rebuild queued as sf-rebuild-agent-hub.service. "
        "This session is ending before post-restart verification.\n"
        "[[P:started:ending the task session after queueing a detached Agent Hub rebuild]]\n"
        "[[P:decision:queued detached Agent Hub rebuild as sf-rebuild-agent-hub.service "
        "and ended before post-restart verification]]\n"
        "[[S:partial:Queued detached Agent Hub rebuild; a fresh post-restart session "
        "must verify health and task completion.]]"
    ]


@pytest.mark.asyncio
async def test_run_tool_loop_preserves_max_turn_finish_reason() -> None:
    state = _ExecutionState(agent_slug="refactor", messages_for_adapter=[])
    tracker = AsyncMock()
    db = AsyncMock()

    class FakeEventStream:
        def __aiter__(self):
            return self._iter()

        async def _iter(self):
            yield types.SimpleNamespace(
                type="assistant",
                message=types.SimpleNamespace(
                    content=[
                        types.SimpleNamespace(
                            type="tool_use",
                            name="Bash",
                            input={"command": "printf 'STEP 1\\n'"},
                            id="tool-1",
                        )
                    ]
                ),
            ), None
            yield types.SimpleNamespace(
                type="tool_result",
                tool_use_id="tool-1",
                content="STEP 1\n",
                is_error=False,
                duration_ms=5,
            ), None
            yield types.SimpleNamespace(
                type="result",
                result="STEP 1",
                finish_reason="max_turns",
            ), None

        async def aclose(self) -> None:
            return None

    adapter = _mock_adapter_with_stream(FakeEventStream())

    with (
        patch(
            "app.api.complete.tool_event_storage.store_tool_use",
            new_callable=AsyncMock,
        ),
        patch(
            "app.api.complete.tool_event_storage.store_tool_result",
            new_callable=AsyncMock,
        ),
    ):
        result = await _run_tool_loop(
            adapter=adapter,
            state=state,
            provider="claude",
            model="claude-sonnet-4-6",
            tools=[],
            tool_catalog=None,
            working_dir=None,
            session_id="session-789",
            loaded_memory_uuids=[],
            db=db,
            tracker=tracker,
            max_turns=1,
            project_id="agent-hub",
        )

    assert result is None
    assert state.turn == 1
    assert state.terminal_finish_reason == "max_turns"


@pytest.mark.asyncio
async def test_run_tool_loop_counts_one_model_turn_for_multiple_tool_results_in_same_response() -> None:
    state = _ExecutionState(agent_slug="refactor", messages_for_adapter=[])
    tracker = AsyncMock()
    db = AsyncMock()

    class FakeEventStream:
        def __aiter__(self):
            return self._iter()

        async def _iter(self):
            yield types.SimpleNamespace(
                type="assistant",
                message=types.SimpleNamespace(
                    content=[
                        types.SimpleNamespace(
                            type="tool_use",
                            name="Bash",
                            input={"command": "printf 'STEP 1\\n'"},
                            id="tool-1",
                        ),
                        types.SimpleNamespace(
                            type="tool_use",
                            name="Bash",
                            input={"command": "printf 'STEP 2\\n'"},
                            id="tool-2",
                        ),
                    ]
                ),
            ), None
            yield types.SimpleNamespace(
                type="tool_result",
                tool_use_id="tool-1",
                content="STEP 1\n",
                is_error=False,
                duration_ms=5,
            ), None
            yield types.SimpleNamespace(
                type="tool_result",
                tool_use_id="tool-2",
                content="STEP 2\n",
                is_error=False,
                duration_ms=5,
            ), None
            yield types.SimpleNamespace(
                type="result",
                result="STEP 1\nSTEP 2",
                finish_reason="max_turns",
            ), None

        async def aclose(self) -> None:
            return None

    adapter = _mock_adapter_with_stream(FakeEventStream())

    with (
        patch(
            "app.api.complete.tool_event_storage.store_tool_use",
            new_callable=AsyncMock,
        ),
        patch(
            "app.api.complete.tool_event_storage.store_tool_result",
            new_callable=AsyncMock,
        ),
    ):
        result = await _run_tool_loop(
            adapter=adapter,
            state=state,
            provider="claude",
            model="claude-sonnet-4-6",
            tools=[],
            tool_catalog=None,
            working_dir=None,
            session_id="session-multi-tool",
            loaded_memory_uuids=[],
            db=db,
            tracker=tracker,
            max_turns=1,
            project_id="agent-hub",
        )

    assert result is None
    assert state.turn == 1
    assert state.tool_calls_count == 2
    assert tracker.report_tool_use.await_args_list[0].args[0] == 1
    assert tracker.report_tool_use.await_args_list[1].args[0] == 1


@pytest.mark.asyncio
async def test_run_tool_loop_counts_one_model_turn_for_batched_top_level_claude_tool_use_blocks() -> None:
    state = _ExecutionState(agent_slug="refactor", messages_for_adapter=[])
    tracker = AsyncMock()
    db = AsyncMock()

    class FakeEventStream:
        def __aiter__(self):
            return self._iter()

        async def _iter(self):
            yield types.SimpleNamespace(
                type="assistant",
                message=types.SimpleNamespace(
                    content=[
                        types.SimpleNamespace(
                            type="tool_use",
                            name="Bash",
                            input={"command": "pwd"},
                            id="tool-1",
                        ),
                        types.SimpleNamespace(
                            type="tool_use",
                            name="Bash",
                            input={"command": "git status --short --branch"},
                            id="tool-2",
                        ),
                    ]
                ),
            ), None
            yield types.SimpleNamespace(
                type="result",
                result="",
                finish_reason="max_turns",
            ), None

        async def aclose(self) -> None:
            return None

    adapter = _mock_adapter_with_stream(FakeEventStream())

    with (
        patch(
            "app.api.complete.tool_event_storage.store_tool_use",
            new_callable=AsyncMock,
        ),
    ):
        result = await _run_tool_loop(
            adapter=adapter,
            state=state,
            provider="claude",
            model="claude-sonnet-4-6",
            tools=[],
            tool_catalog=None,
            working_dir=None,
            session_id="session-batched-claude",
            loaded_memory_uuids=[],
            db=db,
            tracker=tracker,
            max_turns=1,
            project_id="agent-hub",
        )

    assert result is None
    assert state.turn == 1
    assert state.tool_calls_count == 2


@pytest.mark.asyncio
async def test_run_tool_loop_counts_one_model_turn_for_consecutive_assistant_tool_use_events() -> None:
    state = _ExecutionState(agent_slug="refactor", messages_for_adapter=[])
    tracker = AsyncMock()
    db = AsyncMock()

    class FakeEventStream:
        def __aiter__(self):
            return self._iter()

        async def _iter(self):
            yield types.SimpleNamespace(
                type="assistant",
                message=types.SimpleNamespace(
                    content=[
                        types.SimpleNamespace(
                            type="tool_use",
                            name="Bash",
                            input={"command": "st pulse"},
                            id="tool-1",
                        ),
                    ]
                ),
            ), None
            yield types.SimpleNamespace(
                type="assistant",
                message=types.SimpleNamespace(
                    content=[
                        types.SimpleNamespace(
                            type="tool_use",
                            name="Bash",
                            input={"command": "st sessions ownership"},
                            id="tool-2",
                        ),
                    ]
                ),
            ), None
            yield types.SimpleNamespace(
                type="tool_result",
                tool_use_id="tool-1",
                content="PULSE:agent-hub|tasks=0",
                is_error=False,
                duration_ms=5,
            ), None
            yield types.SimpleNamespace(
                type="tool_result",
                tool_use_id="tool-2",
                content="OWNERSHIP[0]",
                is_error=False,
                duration_ms=5,
            ), None
            yield types.SimpleNamespace(
                type="result",
                result="",
                finish_reason="max_turns",
            ), None

        async def aclose(self) -> None:
            return None

    adapter = _mock_adapter_with_stream(FakeEventStream())

    with (
        patch(
            "app.api.complete.tool_event_storage.store_tool_use",
            new_callable=AsyncMock,
        ),
        patch(
            "app.api.complete.tool_event_storage.store_tool_result",
            new_callable=AsyncMock,
        ),
    ):
        result = await _run_tool_loop(
            adapter=adapter,
            state=state,
            provider="claude",
            model="claude-sonnet-4-6",
            tools=[],
            tool_catalog=None,
            working_dir=None,
            session_id="session-consecutive-assistant-events",
            loaded_memory_uuids=[],
            db=db,
            tracker=tracker,
            max_turns=1,
            project_id="agent-hub",
        )

    assert result is None
    assert state.turn == 1
    assert state.tool_calls_count == 2


@pytest.mark.asyncio
async def test_complete_with_tools_returns_error_result_when_finalize_response_is_cancelled() -> None:
    session = _mock_session()
    db = AsyncMock()

    with (
        patch(
            "app.api.complete.tool_handlers.store_user_messages",
            new_callable=AsyncMock,
        ),
        patch(
            "app.api.complete.tool_handlers._run_tool_loop",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.api.complete.tool_handlers.finalize_response",
            new_callable=AsyncMock,
            side_effect=asyncio.CancelledError("finalize cancelled"),
        ),
        patch(
            "app.api.complete.tool_handlers._store_partial_response",
            new_callable=AsyncMock,
        ) as store_partial,
    ):
        from app.api.complete.tool_handlers import _complete_with_tools

        result = await _complete_with_tools(
            adapter=MagicMock(),
            messages=[{"role": "user", "content": "hello"}],
            messages_for_db=[],
            model="claude-sonnet-4-6",
            provider="claude",
            temperature=0.0,
            tools=[],
            tool_catalog=None,
            working_dir=None,
            db=db,
            session=session,
            session_id="session-123",
            is_new_session=True,
            loaded_memory_uuids=[],
            memory_group_id=None,
            progress_callback=None,
            max_turns=1,
            project_id="agent-hub",
        )

    assert result.status == "error"
    assert result.error == "finalize cancelled"
    store_partial.assert_awaited_once()


@pytest.mark.asyncio
async def test_complete_with_tools_passes_shared_closeout_context_to_finalizer() -> None:
    session = _mock_session()
    session.agent_slug = "refactor"
    db = AsyncMock()
    tool_result = types.SimpleNamespace(status="success", content="done")

    with (
        patch(
            "app.api.complete.tool_handlers.store_user_messages",
            new_callable=AsyncMock,
        ),
        patch(
            "app.api.complete.tool_handlers._run_tool_loop",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.api.complete.tool_handlers.finalize_response",
            new_callable=AsyncMock,
            return_value=tool_result,
        ) as mock_finalize,
    ):
        from app.api.complete.tool_handlers import _complete_with_tools

        adapter = MagicMock()
        result = await _complete_with_tools(
            adapter=adapter,
            messages=[{"role": "user", "content": "hello"}],
            messages_for_db=[],
            model="claude-sonnet-4-6",
            provider="claude",
            temperature=0.25,
            tools=[],
            tool_catalog=None,
            working_dir="/home/testuser/agent-hub",
            db=db,
            session=session,
            session_id="session-123",
            is_new_session=True,
            loaded_memory_uuids=[],
            memory_group_id=None,
            progress_callback=None,
            max_turns=1,
            project_id="agent-hub",
        )

    assert result is tool_result
    finalize_args = mock_finalize.await_args
    assert finalize_args is not None
    assert finalize_args.kwargs["adapter"] is adapter
    assert finalize_args.kwargs["temperature"] == 0.25
    assert finalize_args.kwargs["working_dir"] == "/home/testuser/agent-hub"
    assert finalize_args.kwargs["base_messages"][0].role == "user"
    assert finalize_args.kwargs["base_messages"][0].content == "hello"


@pytest.mark.asyncio
async def test_complete_with_tools_returns_error_result_when_partial_store_is_cancelled() -> None:
    session = _mock_session()
    db = AsyncMock()

    with (
        patch(
            "app.api.complete.tool_handlers.store_user_messages",
            new_callable=AsyncMock,
        ),
        patch(
            "app.api.complete.tool_handlers._run_tool_loop",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.api.complete.tool_handlers.finalize_response",
            new_callable=AsyncMock,
            side_effect=asyncio.CancelledError("finalize cancelled"),
        ),
        patch(
            "app.api.complete.tool_handlers._store_partial_response",
            new_callable=AsyncMock,
            side_effect=asyncio.CancelledError("partial store cancelled"),
        ) as store_partial,
    ):
        from app.api.complete.tool_handlers import _complete_with_tools

        result = await _complete_with_tools(
            adapter=MagicMock(),
            messages=[{"role": "user", "content": "hello"}],
            messages_for_db=[],
            model="claude-sonnet-4-6",
            provider="claude",
            temperature=0.0,
            tools=[],
            tool_catalog=None,
            working_dir=None,
            db=db,
            session=session,
            session_id="session-123",
            is_new_session=True,
            loaded_memory_uuids=[],
            memory_group_id=None,
            progress_callback=None,
            max_turns=1,
            project_id="agent-hub",
        )

    assert result.status == "error"
    assert result.error == "finalize cancelled"
    store_partial.assert_awaited_once()
    db.rollback.assert_awaited()


@pytest.mark.asyncio
async def test_complete_with_tools_handles_cancelled_tool_loop() -> None:
    session = _mock_session()
    db = AsyncMock()

    with (
        patch(
            "app.api.complete.tool_handlers._run_tool_loop",
            new_callable=AsyncMock,
            side_effect=asyncio.CancelledError("tool loop cancelled"),
        ),
        patch(
            "app.api.complete.tool_handlers.store_user_messages",
            new_callable=AsyncMock,
        ),
        patch(
            "app.api.complete.tool_handlers._store_partial_response",
            new_callable=AsyncMock,
        ) as store_partial,
    ):
        from app.api.complete.tool_handlers import _complete_with_tools

        result = await _complete_with_tools(
            adapter=MagicMock(),
            messages=[{"role": "user", "content": "hello"}],
            messages_for_db=[],
            temperature=0.0,
            provider="claude",
            model="claude-sonnet-4-6",
            tools=[],
            tool_catalog=None,
            working_dir=None,
            db=db,
            session=session,
            session_id="session-123",
            is_new_session=True,
            loaded_memory_uuids=[],
            memory_group_id=None,
            progress_callback=None,
            max_turns=1,
            project_id="agent-hub",
        )

    assert result is not None
    assert result.status == "error"
    assert result.error == "tool loop cancelled"
    store_partial.assert_awaited_once()
