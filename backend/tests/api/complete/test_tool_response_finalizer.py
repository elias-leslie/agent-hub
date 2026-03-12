from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, sentinel

import pytest

from app.api.complete.tool_response_finalizer import finalize_response


@pytest.mark.asyncio
async def test_finalize_response_replaces_mode_only_closeout_with_tool_summary(mocker) -> None:
    mock_store = mocker.patch(
        "app.api.complete.tool_event_storage.store_assistant_response",
        new_callable=AsyncMock,
    )
    mock_finalize = mocker.patch(
        "app.api.complete.tool_result_builder.finalize_result",
        new_callable=AsyncMock,
        return_value=sentinel.result,
    )
    tracker = SimpleNamespace(report_complete=AsyncMock(), log=[])

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
        tracker=tracker,
        tool_result_summaries=["Bash: PULSE:agent-hub|tasks=0", "Bash: OVERLAPS[0]"],
    )

    assert result is sentinel.result
    stored_content = mock_store.await_args.args[2]
    assert "Tool execution completed" in stored_content
    assert "Bash: PULSE:agent-hub|tasks=0" in stored_content
    assert mock_finalize.await_args.kwargs["content"] == stored_content


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
    tracker = SimpleNamespace(report_complete=AsyncMock(), log=[])

    await finalize_response(
        db=AsyncMock(),
        session=SimpleNamespace(agent_slug="debugger"),
        session_id="sess-2",
        is_new_session=True,
        model="claude-sonnet-4-6",
        provider="claude",
        content_parts=["Verified queue state and overlap risk."],
        thinking_parts=[],
        loaded_memory_uuids=[],
        memory_group_id=None,
        turn=1,
        tool_calls_count=2,
        tracker=tracker,
        tool_result_summaries=["Bash: PULSE:agent-hub|tasks=0"],
    )

    assert mock_store.await_args.args[2] == "Verified queue state and overlap risk."
    assert mock_finalize.await_args.kwargs["content"] == "Verified queue state and overlap risk."
