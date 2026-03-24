from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.api.complete.tool_event_processor import _process_assistant_event


@pytest.mark.asyncio
async def test_process_assistant_event_marks_task_session_missing_progress_tags() -> None:
    event = SimpleNamespace(
        message=SimpleNamespace(
            content=[SimpleNamespace(type="text", text="Investigating the task lane.")]
        )
    )
    db = AsyncMock()
    tracker = AsyncMock()

    with (
        patch(
            "app.api.complete.tool_event_processor._session_requires_progress_tags",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.api.complete.tool_event_processor._extract_narration_from_text",
            new_callable=AsyncMock,
        ) as mock_extract,
        patch(
            "app.api.complete.tool_event_processor.update_session_health",
            new_callable=AsyncMock,
        ) as mock_health,
    ):
        tool_calls = await _process_assistant_event(
            event,
            turn=1,
            session_id="session-1",
            db=db,
            content_parts=[],
            thinking_parts=[],
            tracker=tracker,
            model_used="codex/gpt-5.4",
            agent_id="coder",
        )

    assert tool_calls == 0
    mock_extract.assert_not_awaited()
    assert [call.args[2] for call in mock_health.await_args_list] == [
        "processing_response",
        "progress_tags_missing",
    ]


@pytest.mark.asyncio
async def test_process_assistant_event_marks_task_session_progress_present() -> None:
    event = SimpleNamespace(
        message=SimpleNamespace(
            content=[
                SimpleNamespace(type="text", text="[[P:started:reading the task context]]"),
                SimpleNamespace(type="text", text="[[P:tested:dt -q -d passes clean]]"),
            ]
        )
    )
    db = AsyncMock()
    tracker = AsyncMock()

    with (
        patch(
            "app.api.complete.tool_event_processor._session_requires_progress_tags",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.api.complete.tool_event_processor._extract_narration_from_text",
            new_callable=AsyncMock,
        ) as mock_extract,
        patch(
            "app.api.complete.tool_event_processor.update_session_health",
            new_callable=AsyncMock,
        ) as mock_health,
    ):
        tool_calls = await _process_assistant_event(
            event,
            turn=1,
            session_id="session-2",
            db=db,
            content_parts=[],
            thinking_parts=[],
            tracker=tracker,
            model_used="codex/gpt-5.4",
            agent_id="coder",
        )

    assert tool_calls == 0
    assert mock_extract.await_count == 2
    assert [call.args[2] for call in mock_health.await_args_list] == [
        "processing_response",
        "progress_tags_present",
    ]
