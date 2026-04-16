from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, sentinel

import pytest

from app.adapters.base import Message
from app.api.complete.tool_response_finalizer import finalize_response
from app.services.token_counter import count_message_tokens


def _tracker() -> SimpleNamespace:
    return SimpleNamespace(report_complete=AsyncMock(), report_status=AsyncMock(), log=[])


@pytest.mark.asyncio
async def test_finalize_response_requests_final_closeout_for_placeholder_tool_summary(mocker) -> None:
    mock_store = mocker.patch(
        "app.api.complete.tool_event_storage.store_assistant_response",
        new_callable=AsyncMock,
    )
    mock_finalize = mocker.patch(
        "app.api.complete.tool_result_builder.finalize_result",
        new_callable=AsyncMock,
        return_value=sentinel.result,
    )
    adapter = SimpleNamespace(
        complete=AsyncMock(
            return_value=SimpleNamespace(
                content="Verified queue state and overlap risk.",
                thinking_content=None,
                tool_calls=[],
            )
        )
    )

    result = await finalize_response(
        db=AsyncMock(),
        session=SimpleNamespace(agent_slug="refactor"),
        session_id="sess-1",
        is_new_session=True,
        model="claude-sonnet-4-6",
        provider="claude",
        content_parts=["Mode: campaign"],
        thinking_parts=[],
        loaded_memory_uuids=[],
        memory_group_id=None,
        turn=2,
        tool_calls_count=3,
        finish_reason="end_turn",
        tracker=_tracker(),
        adapter=adapter,
        base_messages=[Message(role="user", content="Do a minimal coordination check.")],
        temperature=0.0,
        working_dir="/home/testuser/agent-hub",
        tool_result_summaries=["Bash: PULSE:agent-hub|tasks=0", "Bash: OVERLAPS[0]"],
    )

    assert result is sentinel.result
    adapter.complete.assert_awaited_once()
    recovery_messages = adapter.complete.await_args.kwargs["messages"]
    assert recovery_messages[-1].role == "user"
    assert "Captured observations:" in recovery_messages[-1].content
    assert "Mode: campaign" in recovery_messages[-1].content
    assert mock_store.await_args.args[2] == "Verified queue state and overlap risk."
    assert mock_finalize.await_args.kwargs["fallback_used"] is False


@pytest.mark.asyncio
async def test_finalize_response_recovery_success_bypasses_deterministic_fallback(mocker) -> None:
    mock_store = mocker.patch(
        "app.api.complete.tool_event_storage.store_assistant_response",
        new_callable=AsyncMock,
    )
    mock_finalize = mocker.patch(
        "app.api.complete.tool_result_builder.finalize_result",
        new_callable=AsyncMock,
        return_value=sentinel.result,
    )
    tracker = _tracker()
    adapter = SimpleNamespace(
        complete=AsyncMock(
            return_value=SimpleNamespace(
                content="No further changes were needed. Verified pulse and overlap state.",
                thinking_content="closeout reasoning",
                tool_calls=[],
            )
        )
    )

    await finalize_response(
        db=AsyncMock(),
        session=SimpleNamespace(agent_slug="refactor"),
        session_id="sess-2",
        is_new_session=True,
        model="claude-sonnet-4-6",
        provider="claude",
        content_parts=["Mode: campaign"],
        thinking_parts=["initial reasoning"],
        loaded_memory_uuids=[],
        memory_group_id=None,
        turn=2,
        tool_calls_count=1,
        finish_reason="end_turn",
        tracker=tracker,
        adapter=adapter,
        base_messages=[Message(role="user", content="Do a minimal coordination check.")],
        temperature=0.0,
        working_dir=None,
        tool_result_summaries=["Bash: PULSE:agent-hub|tasks=0"],
    )

    stored_content = mock_store.await_args.args[2]
    assert stored_content == "No further changes were needed. Verified pulse and overlap state."
    assert "Tool execution completed" not in stored_content
    assert tracker.report_status.await_count == 1
    assert mock_finalize.await_args.kwargs["thinking_content"] == "initial reasoning\ncloseout reasoning"
    assert mock_finalize.await_args.kwargs["fallback_used"] is False
    assert mock_finalize.await_args.kwargs["fallback_reason"] is None


@pytest.mark.asyncio
async def test_finalize_response_recovers_narration_only_tool_closeout(mocker) -> None:
    mock_store = mocker.patch(
        "app.api.complete.tool_event_storage.store_assistant_response",
        new_callable=AsyncMock,
    )
    mock_finalize = mocker.patch(
        "app.api.complete.tool_result_builder.finalize_result",
        new_callable=AsyncMock,
        return_value=sentinel.result,
    )
    tracker = _tracker()
    adapter = SimpleNamespace(
        complete=AsyncMock(
            return_value=SimpleNamespace(
                content="Published summitflow commit ddd08c64c after focused tests passed; full repo type gate still fails from unrelated pre-existing errors.",
                thinking_content=None,
                tool_calls=[],
            )
        )
    )

    await finalize_response(
        db=AsyncMock(),
        session=SimpleNamespace(agent_slug="persona"),
        session_id="sess-narration",
        is_new_session=True,
        model="codex/gpt-5.4",
        provider="codex",
        content_parts=[
            "[[P:started]] Inspect repo state. Pick small ready task."
            "[[P:tested]] Focused pytest pass."
            "[[P:decision]] commit.sh allowed with skip-checks only path past unrelated gate break."
        ],
        thinking_parts=[],
        loaded_memory_uuids=[],
        memory_group_id=None,
        turn=2,
        tool_calls_count=3,
        finish_reason="end_turn",
        tracker=tracker,
        adapter=adapter,
        base_messages=[Message(role="user", content="Take one summitflow task to completion or report blocker only.")],
        temperature=0.0,
        working_dir="/srv/workspaces/projects/summitflow",
        tool_result_summaries=["Bash: commit.sh --current --skip-checks --msg ... -> SUCCESS"],
    )

    stored_content = mock_store.await_args.args[2]
    assert stored_content.startswith("Published summitflow commit ddd08c64c")
    assert tracker.report_status.await_count == 1
    assert mock_finalize.await_args.kwargs["fallback_used"] is False


@pytest.mark.asyncio
async def test_finalize_response_falls_back_when_closeout_recovery_fails(mocker) -> None:
    mock_store = mocker.patch(
        "app.api.complete.tool_event_storage.store_assistant_response",
        new_callable=AsyncMock,
    )
    mock_finalize = mocker.patch(
        "app.api.complete.tool_result_builder.finalize_result",
        new_callable=AsyncMock,
        return_value=sentinel.result,
    )
    tracker = _tracker()
    adapter = SimpleNamespace(complete=AsyncMock(side_effect=RuntimeError("provider unavailable")))

    await finalize_response(
        db=AsyncMock(),
        session=SimpleNamespace(agent_slug="refactor"),
        session_id="sess-3",
        is_new_session=True,
        model="claude-sonnet-4-6",
        provider="claude",
        content_parts=["Mode: campaign"],
        thinking_parts=[],
        loaded_memory_uuids=[],
        memory_group_id=None,
        turn=3,
        tool_calls_count=2,
        finish_reason="max_turns",
        tracker=tracker,
        adapter=adapter,
        base_messages=[Message(role="user", content="Do a minimal coordination check.")],
        temperature=0.0,
        working_dir=None,
        tool_result_summaries=["Bash: PULSE:agent-hub|tasks=0", "Bash: OVERLAPS[0]"],
    )

    stored_content = mock_store.await_args.args[2]
    assert "Tool execution completed" in stored_content
    assert "Bash: PULSE:agent-hub|tasks=0" in stored_content
    assert tracker.report_status.await_count == 2
    assert mock_finalize.await_args.kwargs["fallback_used"] is True
    assert mock_finalize.await_args.kwargs["fallback_reason"] == "tool_closeout_recovery_error"


@pytest.mark.asyncio
async def test_finalize_response_preserves_substantive_content(mocker) -> None:
    mock_store = mocker.patch(
        "app.api.complete.tool_event_storage.store_assistant_response",
        new_callable=AsyncMock,
    )
    mock_finalize = mocker.patch(
        "app.api.complete.tool_result_builder.finalize_result",
        new_callable=AsyncMock,
        return_value=sentinel.result,
    )
    adapter = SimpleNamespace(complete=AsyncMock())

    await finalize_response(
        db=AsyncMock(),
        session=SimpleNamespace(agent_slug="debugger"),
        session_id="sess-4",
        is_new_session=True,
        model="claude-sonnet-4-6",
        provider="claude",
        content_parts=["Verified queue state and overlap risk."],
        thinking_parts=[],
        loaded_memory_uuids=[],
        memory_group_id=None,
        turn=1,
        tool_calls_count=2,
        finish_reason="end_turn",
        tracker=_tracker(),
        adapter=adapter,
        base_messages=[Message(role="user", content="Do a minimal coordination check.")],
        temperature=0.0,
        working_dir=None,
        tool_result_summaries=["Bash: PULSE:agent-hub|tasks=0"],
    )

    adapter.complete.assert_not_awaited()
    assert mock_store.await_args.args[2] == "Verified queue state and overlap risk."
    assert mock_finalize.await_args.kwargs["content"] == "Verified queue state and overlap risk."


@pytest.mark.asyncio
async def test_finalize_response_normalizes_terminal_summary_tag_near_miss(mocker) -> None:
    mock_store = mocker.patch(
        "app.api.complete.tool_event_storage.store_assistant_response",
        new_callable=AsyncMock,
    )
    mock_finalize = mocker.patch(
        "app.api.complete.tool_result_builder.finalize_result",
        new_callable=AsyncMock,
        return_value=sentinel.result,
    )

    await finalize_response(
        db=AsyncMock(),
        session=SimpleNamespace(agent_slug="coder"),
        session_id="sess-near-miss",
        is_new_session=True,
        model="codex/gpt-5.4",
        provider="codex",
        content_parts=["main\n[[S:completed:Reported the current git branch name]}"],
        thinking_parts=[],
        loaded_memory_uuids=[],
        memory_group_id=None,
        turn=2,
        tool_calls_count=1,
        finish_reason="stop",
        tracker=_tracker(),
        adapter=SimpleNamespace(complete=AsyncMock()),
        base_messages=[Message(role="user", content="Print ONLY the current git branch name.")],
        temperature=0.0,
        working_dir="/srv/workspaces/projects/agent-hub",
        tool_result_summaries=["Bash: main"],
    )

    stored_content = mock_store.await_args.args[2]
    assert stored_content == "main\n[[S:completed:Reported the current git branch name]]"
    assert mock_finalize.await_args.kwargs["content"] == stored_content


@pytest.mark.asyncio
async def test_finalize_response_dedupes_exact_repeated_closeout_block(mocker) -> None:
    mock_store = mocker.patch(
        "app.api.complete.tool_event_storage.store_assistant_response",
        new_callable=AsyncMock,
    )
    mock_finalize = mocker.patch(
        "app.api.complete.tool_result_builder.finalize_result",
        new_callable=AsyncMock,
        return_value=sentinel.result,
    )
    repeated = (
        "[[P:started:reviewing test3 cleanup and ready work]]\n"
        "HEARTBEAT_ACTION Dispatched task-fa0425ec and retired stale residue.\n"
        "[[S:completed:Queued the test3 lane and cleared the matching cleanup items.]]"
    )

    await finalize_response(
        db=AsyncMock(),
        session=SimpleNamespace(agent_slug="persona"),
        session_id="sess-dedupe",
        is_new_session=True,
        model="codex/gpt-5.4",
        provider="codex",
        content_parts=[repeated + repeated],
        thinking_parts=[],
        loaded_memory_uuids=[],
        memory_group_id=None,
        turn=3,
        tool_calls_count=2,
        finish_reason="stop",
        tracker=_tracker(),
        adapter=SimpleNamespace(complete=AsyncMock()),
        base_messages=[Message(role="user", content="Run the heartbeat now.")],
        temperature=0.0,
        working_dir="/srv/workspaces/projects/agent-hub",
        tool_result_summaries=["manage_tasks: queued task-fa0425ec"],
    )

    stored_content = mock_store.await_args.args[2]
    assert stored_content == repeated
    assert mock_finalize.await_args.kwargs["content"] == repeated


@pytest.mark.asyncio
async def test_finalize_response_prefers_progress_turns_for_reported_turn_count(mocker) -> None:
    mocker.patch(
        "app.api.complete.tool_event_storage.store_assistant_response",
        new_callable=AsyncMock,
    )
    mock_finalize = mocker.patch(
        "app.api.complete.tool_result_builder.finalize_result",
        new_callable=AsyncMock,
        return_value=sentinel.result,
    )
    tracker = _tracker()
    tracker.log.extend(
        [
            SimpleNamespace(turn=1, status="tool_use", message="Using tool: Bash"),
            SimpleNamespace(turn=2, status="tool_use", message="Using tool: Bash"),
            SimpleNamespace(turn=4, status="tool_use", message="Using tool: Bash"),
        ]
    )

    await finalize_response(
        db=AsyncMock(),
        session=SimpleNamespace(agent_slug="debugger"),
        session_id="sess-5",
        is_new_session=True,
        model="claude-sonnet-4-6",
        provider="claude",
        content_parts=["Verified queue state and overlap risk."],
        thinking_parts=[],
        loaded_memory_uuids=[],
        memory_group_id=None,
        turn=8,
        tool_calls_count=3,
        finish_reason="max_turns",
        tracker=tracker,
        adapter=SimpleNamespace(complete=AsyncMock()),
        base_messages=[Message(role="user", content="Do a minimal coordination check.")],
        temperature=0.0,
        working_dir=None,
        tool_result_summaries=["Bash: OVERLAPS[0]"],
    )

    tracker.report_complete.assert_awaited_once_with(4, 3)
    assert mock_finalize.await_args.kwargs["turn"] == 4


@pytest.mark.asyncio
async def test_finalize_response_passes_estimated_input_tokens(mocker) -> None:
    mocker.patch(
        "app.api.complete.tool_event_storage.store_assistant_response",
        new_callable=AsyncMock,
    )
    mock_finalize = mocker.patch(
        "app.api.complete.tool_result_builder.finalize_result",
        new_callable=AsyncMock,
        return_value=sentinel.result,
    )
    base_messages = [
        Message(role="system", content="Follow the repo rules."),
        Message(role="user", content="Inspect the current queue state."),
    ]

    await finalize_response(
        db=AsyncMock(),
        session=SimpleNamespace(agent_slug="debugger"),
        session_id="sess-input-tokens",
        is_new_session=True,
        model="claude-sonnet-4-6",
        provider="claude",
        content_parts=["Verified queue state and overlap risk."],
        thinking_parts=[],
        loaded_memory_uuids=[],
        memory_group_id=None,
        turn=1,
        tool_calls_count=1,
        finish_reason="end_turn",
        tracker=_tracker(),
        adapter=SimpleNamespace(complete=AsyncMock()),
        base_messages=base_messages,
        temperature=0.0,
        working_dir=None,
        tool_result_summaries=["Bash: PULSE:agent-hub|tasks=0"],
    )

    assert (
        mock_finalize.await_args.kwargs["estimated_input_tokens"]
        == count_message_tokens(
            [{"role": message.role, "content": message.content} for message in base_messages]
        )
    )
