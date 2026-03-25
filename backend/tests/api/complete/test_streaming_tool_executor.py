from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.complete.streaming_context import StreamContext
from app.api.complete.streaming_tool_executor import _iter_tool_execution
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

    chunks = [
        chunk
        async for chunk in _iter_tool_execution(event, handler, _build_context(), result_out)
    ]

    assert handler.execute.await_count == 1
    assert result_out == [("tool-1", "bash", "ok", False)]
    assert any('"type":"tool_start"' in chunk for chunk in chunks)
    assert any('"type":"tool_result"' in chunk for chunk in chunks)


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
