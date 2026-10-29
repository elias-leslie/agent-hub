"""A streamed turn's thinking and tool calls are stored between its prompt and its answer."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.api.complete.event_helpers import TurnTraceStep, save_events
from app.services.event_storage import TOOL_RESULT_SUMMARY_CHARS


@pytest.mark.asyncio
async def test_save_events_stores_the_trace_in_order_before_the_answer() -> None:
    calls: list[str] = []

    def recorder(name: str) -> AsyncMock:
        async def record(*_args: object, **kwargs: object) -> None:
            calls.append(name)
            recorded[name] = kwargs

        return AsyncMock(side_effect=record)

    recorded: dict[str, dict[str, object]] = {}
    long_result = "x" * (TOOL_RESULT_SUMMARY_CHARS + 500)
    trace = [
        TurnTraceStep(kind="thinking", text="look first"),
        TurnTraceStep(kind="tool_use", tool_name="read", call_id="c1", tool_input={"path": "a"}),
        TurnTraceStep(kind="tool_result", text=long_result, tool_name="read", call_id="c1", duration_ms=7),
    ]
    results: list[tuple[str, dict[str, Any], object, object]] = []

    async def result_event(_db: object, _sid: str, name: str, output: dict[str, Any], **kwargs: object) -> None:
        calls.append("tool_result")
        results.append((name, output, kwargs.get("call_id"), kwargs.get("duration_ms")))

    with (
        patch("app.api.complete.event_helpers.store_message_event", new=recorder("message")),
        patch("app.api.complete.event_helpers.store_thinking_event", new=recorder("thinking")),
        patch("app.api.complete.event_helpers.store_tool_use_event", new=recorder("tool_use")),
        patch("app.api.complete.event_helpers.store_tool_result_event", new=result_event),
    ):
        db = AsyncMock()
        await save_events(
            db, "s1", [], "answer", 1, 1, model_used="m", agent_id="chat", trace=trace, thinking_tokens=42,
        )

    assert calls == ["thinking", "tool_use", "tool_result", "message"]
    assert recorded["thinking"]["tokens"] == 42
    assert recorded["tool_use"]["call_id"] == "c1"
    name, output, call_id, duration = results[0]
    assert (name, call_id, duration) == ("read", "c1", 7)
    # Stored results are bounded by the same limit the history response uses.
    assert output["is_error"] is False
    assert len(str(output["content"])) == TOOL_RESULT_SUMMARY_CHARS + 1
    assert str(output["content"]).endswith("…")


@pytest.mark.asyncio
async def test_save_events_stores_each_tool_calls_place_in_the_answer_and_the_thinking_time() -> None:
    seen: dict[str, dict[str, object]] = {}

    def recorder(name: str) -> AsyncMock:
        async def record(*_args: object, **kwargs: object) -> None:
            seen[name] = kwargs

        return AsyncMock(side_effect=record)

    trace = [
        TurnTraceStep(kind="thinking", text="hm", duration_ms=2500),
        TurnTraceStep(kind="tool_use", tool_name="read", call_id="c1", tool_input={}, content_offset=14),
    ]
    with (
        patch("app.api.complete.event_helpers.store_message_event", new=recorder("message")),
        patch("app.api.complete.event_helpers.store_thinking_event", new=recorder("thinking")),
        patch("app.api.complete.event_helpers.store_tool_use_event", new=recorder("tool_use")),
    ):
        await save_events(AsyncMock(), "s1", [], "answer", 1, 1, model_used="m", agent_id="chat", trace=trace)

    assert seen["thinking"]["duration_ms"] == 2500
    assert seen["tool_use"]["content_offset"] == 14
