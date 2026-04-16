from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, patch

import pytest

from app.api.complete.streaming_context import StreamContext
from app.api.complete.streaming_tool_executor import _iter_tool_execution, collect_turn_events
from app.services.tools.base import ToolResult


def _build_context(*, cancelled: bool = False) -> StreamContext:
    ctx = StreamContext(
        session_id="sess-1",
        model="codex/gpt-5.4",
        provider="codex",
        agent_used="coder",
        model_used="codex/gpt-5.4",
        fallback_used=False,
        user_messages=[],
        stream_start=time.monotonic(),
        is_new_session=False,
        is_one_shot=False,
    )
    if cancelled:
        import asyncio

        ctx.cancel_event = asyncio.Event()
        ctx.cancel_event.set()
    return ctx


@pytest.mark.asyncio
async def test_iter_tool_execution_executes_handler_once_and_emits_result() -> None:
    handler = AsyncMock()
    handler.execute = AsyncMock(
        return_value=ToolResult(
            tool_use_id="tool-1",
            content="ok",
            is_error=False,
            duration_ms=12,
        )
    )
    event = SimpleNamespace(tool_name="bash", tool_id="tool-1", tool_input={"command": "pwd"})
    result_out: list[tuple[str, str, str, bool]] = []

    with (
        patch(
            "app.api.complete.streaming_tool_executor.mirror_stream_tool_use",
            new_callable=AsyncMock,
        ) as mock_mirror_tool_use,
        patch(
            "app.api.complete.streaming_tool_executor.mirror_stream_tool_result",
            new_callable=AsyncMock,
        ) as mock_mirror_tool_result,
    ):
        chunks = [
            chunk
            async for chunk in _iter_tool_execution(event, handler, _build_context(), result_out)
        ]

    assert handler.execute.await_count == 1
    assert result_out == [("tool-1", "bash", "ok", False)]
    assert any('"type":"tool_start"' in chunk for chunk in chunks)
    assert any('"type":"tool_result"' in chunk for chunk in chunks)
    mock_mirror_tool_use.assert_awaited_once_with(ANY, "bash", {"command": "pwd"})
    mock_mirror_tool_result.assert_awaited_once_with(
        ANY,
        "bash",
        "ok",
        duration_ms=12,
        is_error=False,
    )


@pytest.mark.asyncio
async def test_iter_tool_execution_short_circuits_when_cancelled() -> None:
    handler = AsyncMock()
    handler.execute = AsyncMock()
    event = SimpleNamespace(tool_name="bash", tool_id="tool-1", tool_input={"command": "pwd"})
    result_out: list[tuple[str, str, str, bool]] = []

    chunks = [
        chunk
        async for chunk in _iter_tool_execution(event, handler, _build_context(cancelled=True), result_out)
    ]

    assert handler.execute.await_count == 0
    assert result_out == []
    assert len(chunks) == 1
    assert '"type":"cancelled"' in chunks[0]


@pytest.mark.asyncio
async def test_collect_turn_events_publishes_initial_stream_progress_once() -> None:
    class FakeAdapter:
        async def stream(self, **_kwargs):
            yield SimpleNamespace(type="content", content="first chunk")
            yield SimpleNamespace(type="content", content=" more text")
            yield SimpleNamespace(type="done", input_tokens=1, output_tokens=1, finish_reason="stop")

    with patch(
        "app.api.complete.streaming_tool_executor.publish_stream_progress",
        new_callable=AsyncMock,
    ) as mock_publish_progress:
        sse_parts, pending, resolved, turn_text, done_event = await collect_turn_events(
            FakeAdapter(),
            current_messages=[],
            model="codex/gpt-5.4",
            max_tokens=None,
            temperature=1.0,
            stream_kwargs={},
            content_buf=[""],
            ctx=_build_context(),
        )

    assert len(sse_parts) == 2
    assert pending == []
    assert resolved == set()
    assert turn_text == "first chunk more text"
    assert done_event is not None
    mock_publish_progress.assert_awaited_once_with(ANY, "first chunk")
