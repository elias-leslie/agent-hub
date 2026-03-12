from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.adapters.base import Message
from app.api.complete.streaming_context import StreamContext
from app.api.complete.streaming_tool_loop import iter_stream_sse_with_tools


@pytest.mark.asyncio
async def test_iter_stream_sse_with_tools_retries_empty_done_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.complete import streaming_tool_loop as mod

    captured_messages: list[list[Message]] = []
    content_buf = [""]

    async def fake_collect_turn_events(
        adapter: object,
        current_messages: list[Message],
        model: str,
        max_tokens: int | None,
        temperature: float,
        stream_kwargs: dict[str, object],
        content_buf_arg: list[str],
        ctx: StreamContext,
    ) -> tuple[list[str], list[object], set[str], str, object | None]:
        captured_messages.append(list(current_messages))
        if len(captured_messages) == 1:
            return [], [], set(), "", SimpleNamespace(
                input_tokens=1,
                output_tokens=1,
                finish_reason="end_turn",
            )
        content_buf_arg[0] = "Final response"
        return [], [], set(), "Final response", SimpleNamespace(
            input_tokens=2,
            output_tokens=3,
            finish_reason="end_turn",
        )

    monkeypatch.setattr(mod, "collect_turn_events", fake_collect_turn_events)
    monkeypatch.setattr(
        "app.services.tools.tool_handler.create_direct_handler",
        lambda **kwargs: AsyncMock(),
    )
    build_done = AsyncMock(return_value="data: done\n\n")
    monkeypatch.setattr(mod, "build_done_sse", build_done)

    ctx = StreamContext(
        session_id="sess-1",
        model="codex/gpt-5.4",
        provider="codex",
        agent_used="memory-curator",
        model_used="codex/gpt-5.4",
        fallback_used=False,
        user_messages=[],
        stream_start=time.monotonic(),
        is_new_session=False,
        is_one_shot=False,
    )

    chunks = []
    async for chunk in iter_stream_sse_with_tools(
        adapter=object(),
        messages=[Message(role="user", content="Curate memory")],
        model="codex/gpt-5.4",
        max_tokens=None,
        temperature=0.2,
        stream_kwargs={},
        content_buf=content_buf,
        ctx=ctx,
        project_id="agent-hub",
        max_tool_turns=3,
    ):
        chunks.append(chunk)

    assert len(captured_messages) == 2
    assert captured_messages[1][-2].role == "assistant"
    assert captured_messages[1][-1].role == "user"
    assert "final user-facing response" in captured_messages[1][-1].content.lower()
    build_done.assert_awaited_once()
    assert chunks == ["data: done\n\n"]
