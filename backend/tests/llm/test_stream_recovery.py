"""A model call ends only on a definite death signal; thinking, silence and big payloads never end one."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.llm import tool_loop
from app.llm.model_resolver import resolve_llm_model
from app.llm.providers import openai_codex_responses as codex
from app.llm.types import (
    AssistantMessage,
    Context,
    SimpleStreamOptions,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from app.llm.utils.outcomes import outcome_of
from app.llm.utils.request_metrics import request_metrics_of

KEEPALIVE = {"type": "keepalive"}
TEXT = [{"type": "response.output_text.delta", "delta": "hi"}, {"type": "response.completed", "response": {}}]
# Text, then the connection closes without response.completed.
EOF_AFTER_TEXT = [{"type": "response.output_text.delta", "delta": "half"}]
TOOL_CALL = [
    {"type": "response.output_item.added", "item": {"type": "function_call", "call_id": "c1", "name": "bash"}},
    {"type": "response.function_call_arguments.delta", "call_id": "c1", "delta": '{"command":"ls"}'},
    {
        "type": "response.output_item.done",
        "item": {"type": "function_call", "call_id": "c1", "id": "fc_1", "name": "bash", "arguments": '{"command":"ls"}'},
    },
    {"type": "response.completed", "response": {}},
]


@pytest.fixture
def sse(monkeypatch: pytest.MonkeyPatch):
    """Script the SSE items of each request in order; returns the request counter."""
    monkeypatch.setattr(tool_loop, "retry_delay", lambda _attempt: 0)

    def script(*requests: list[Any]) -> list[int]:
        calls = [0]

        @asynccontextmanager
        async def authenticated_response(*_args):
            yield SimpleNamespace(status_code=200)

        async def lines(_response) -> AsyncIterator[dict]:
            index = calls[0]
            calls[0] += 1
            for item in requests[index]:
                if isinstance(item, BaseException):
                    raise item
                yield item

        monkeypatch.setattr(codex, "_authenticated_response", authenticated_response)
        monkeypatch.setattr(codex, "_parse_sse_lines", lines)
        return calls

    return script


def _kind(message: Any) -> str | None:
    outcome = outcome_of(message)
    return outcome.kind if outcome else None


def _model():
    return resolve_llm_model("codex/gpt-6.1-sol", "codex")


async def _complete(**options) -> tuple[AssistantMessage, list]:
    stream = codex.openai_codex_responses_provider.stream_simple(_model(), Context(messages=[]), SimpleStreamOptions(**options))
    events = [event async for event in stream]
    return await stream.result(), events


async def _turn(**options) -> tuple[list, list[AssistantMessage]]:
    sunk: list[AssistantMessage] = []
    events = [e async for e in tool_loop.run_turn(_model(), Context(messages=[]), SimpleStreamOptions(**options), sunk)]
    return events, sunk


@pytest.mark.asyncio
async def test_a_keepalive_only_stream_longer_than_the_old_timeout_is_not_ended(
    sse, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [0.0]
    monkeypatch.setattr(codex, "time", SimpleNamespace(monotonic=lambda: clock[0], time=lambda: 0.0))
    calls = sse([])

    async def thinking(_response) -> AsyncIterator[dict]:
        calls[0] += 1
        for _ in range(8):  # 8 keepalives 30s apart: 240s of silence from the model, past the old 90s limit
            clock[0] += 30
            yield KEEPALIVE
            await asyncio.sleep(0.01)
        yield TEXT[0]
        yield TEXT[1]

    monkeypatch.setattr(codex, "_parse_sse_lines", thinking)

    result, _ = await _complete(max_retries=0)

    assert (calls[0], result.stop_reason, outcome_of(result)) == (1, "stop", None)
    metrics = request_metrics_of(result)
    assert metrics is not None
    assert (metrics["keepalives"], metrics["max_gap_s"], metrics["outcome"]) == (8, 30.0, "ok")
    assert metrics["max_event_gap_s"] == 240.0


@pytest.mark.asyncio
async def test_a_long_silence_between_events_is_not_a_death(sse, monkeypatch: pytest.MonkeyPatch) -> None:
    sse(TEXT)

    async def slow(_response) -> AsyncIterator[dict]:
        yield {"type": "response.created"}
        await asyncio.sleep(0.3)  # no frame at all: the transport bound (httpx read timeout) is the only judge
        for item in TEXT:
            yield item

    monkeypatch.setattr(codex, "_parse_sse_lines", slow)

    result, _ = await _complete(max_retries=0)

    assert result.stop_reason == "stop"


@pytest.mark.asyncio
async def test_eof_before_completion_is_an_interrupted_error_not_a_partial_answer(sse) -> None:
    sse(EOF_AFTER_TEXT)

    result, events = await _complete()

    assert result.stop_reason == "error"
    assert result.error_message == "stream ended before response.completed"
    assert _kind(result) == "interrupted"
    assert "done" not in [e.type for e in events]


@pytest.mark.asyncio
async def test_a_dropped_connection_is_interrupted(sse) -> None:
    sse([*TEXT[:1], httpx.RemoteProtocolError("dropped")])

    result, _ = await _complete()

    assert (result.stop_reason, result.error_message) == ("error", "dropped")
    assert _kind(result) == "interrupted"


@pytest.mark.asyncio
async def test_a_large_tool_call_passes_through_untouched(sse) -> None:
    content = "x" * 200_000  # well past the old 65,536-char cap
    arguments = json.dumps({"content": content})
    deltas = [
        {"type": "response.function_call_arguments.delta", "call_id": "c1", "delta": arguments[i : i + 4096]}
        for i in range(0, len(arguments), 4096)
    ]
    done = {
        "type": "response.output_item.done",
        "item": {"type": "function_call", "call_id": "c1", "id": "fc_1", "name": "write", "arguments": arguments},
    }
    calls = sse([TOOL_CALL[0], *deltas, done, TOOL_CALL[3]])

    result, _ = await _complete(max_retries=0)

    assert calls[0] == 1 and result.stop_reason == "toolUse"
    call = next(b for b in result.content if isinstance(b, ToolCall))
    assert call.arguments == {"content": content}
    metrics = request_metrics_of(result)
    assert metrics is not None and metrics["max_tool_args"] == len(arguments)


@pytest.mark.asyncio
async def test_the_request_metrics_record_is_compact_and_complete(sse) -> None:
    sse([KEEPALIVE, KEEPALIVE, *TOOL_CALL])

    result, _ = await _complete(max_retries=0)

    metrics = request_metrics_of(result)
    assert metrics is not None
    assert {"max_gap_s", "max_event_gap_s", "keepalives", "max_tool_args", "events", "total_s", "outcome"} <= metrics.keys()
    assert (metrics["keepalives"], metrics["max_tool_args"], metrics["outcome"]) == (2, len('{"command":"ls"}'), "ok")


@pytest.mark.asyncio
async def test_the_provider_never_resends_on_its_own(sse) -> None:
    calls = sse([httpx.ReadTimeout("stalled")], TEXT)

    result, _ = await _complete(max_retries=5)

    assert (calls[0], result.stop_reason, _kind(result)) == (1, "error", "interrupted")


@pytest.mark.asyncio
async def test_a_turn_cut_off_by_eof_is_resent_and_the_partial_is_voided(sse) -> None:
    calls = sse(EOF_AFTER_TEXT, TEXT)

    events, sunk = await _turn()

    assert calls[0] == 2 and sunk[0].stop_reason == "stop"
    retries = [e for e in events if isinstance(e, tool_loop.TurnRetry)]
    assert [(r.attempt, r.max_retries) for r in retries] == [(1, 5)]
    assert retries[0].reason == "stream ended before response.completed"
    kinds = [e.type for e in events]
    assert kinds.index("turn_retry") > kinds.index("text_delta") and "error" not in kinds
    assert [b.text for b in sunk[0].content if isinstance(b, TextContent)] == ["hi"]
    metrics = request_metrics_of(sunk[0])
    assert metrics is not None and metrics["retries"] == 1
    assert metrics["retry_log"][0]["reason"] == "stream ended before response.completed"


@pytest.mark.asyncio
async def test_the_loop_surfaces_the_error_once_the_retry_budget_is_spent(sse) -> None:
    calls = sse(*[[httpx.ReadTimeout("stalled")]] * 3)

    events, sunk = await _turn(max_retries=1)

    assert calls[0] == 2
    assert [type(e).__name__ for e in events].count("TurnRetry") == 1
    assert events[-1].type == "error" and _kind(events[-1].error) == "interrupted"
    assert _kind(sunk[0]) == "interrupted" and [e.type for e in events].count("error") == 1
    metrics = request_metrics_of(sunk[0])
    assert metrics is not None and metrics["retries"] == 1 and metrics["outcome"].startswith("ReadTimeout")


@pytest.mark.asyncio
async def test_the_default_budget_comes_from_settings(sse, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "llm_stream_max_retries", 3)
    calls = sse(*[[httpx.ReadTimeout("stalled")]] * 6)

    events, _ = await _turn()

    assert calls[0] == 4 and [type(e).__name__ for e in events].count("TurnRetry") == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event",
    [
        {"type": "response.failed", "response": {"error": {"code": "cyber_policy", "message": "flagged"}}},
        {"type": "response.failed", "response": {"error": {"code": "usage_limit_reached", "message": "limit"}}},
        {"type": "response.failed", "response": {"error": {"code": "context_length_exceeded", "message": "long"}}},
    ],
)
async def test_refusals_and_fatal_errors_are_not_resent(sse, event: dict) -> None:
    calls = sse([event], TEXT)

    events, sunk = await _turn()

    assert calls[0] == 1 and sunk[0].stop_reason == "error"
    assert not [e for e in events if isinstance(e, tool_loop.TurnRetry)]


@pytest.mark.asyncio
async def test_a_failed_response_with_a_server_error_code_is_resent(sse) -> None:
    calls = sse([{"type": "response.failed", "response": {"error": {"code": "server_error", "message": "boom"}}}], TEXT)

    _, sunk = await _turn()

    assert calls[0] == 2 and sunk[0].stop_reason == "stop"


@pytest.mark.asyncio
async def test_the_tool_loop_reruns_an_interrupted_turn_and_drops_the_partial(sse) -> None:
    calls = sse(EOF_AFTER_TEXT, TOOL_CALL, TEXT)
    context = Context(messages=[UserMessage(content="go", timestamp=0)])

    async def run_tool(call: ToolCall) -> ToolResultMessage:
        return ToolResultMessage(tool_call_id=call.id, tool_name=call.name, content=[TextContent(text="ok")], is_error=False, timestamp=0)

    events = [e async for e in tool_loop.run(_model(), context, run_tool)]

    assert calls[0] == 3
    assert [type(e).__name__ for e in events].count("TurnRetry") == 1
    assert "error" not in [e.type for e in events]
    assert [type(m).__name__ for m in context.messages] == ["UserMessage", "AssistantMessage", "ToolResultMessage", "AssistantMessage"]
    assert all(outcome_of(m) is None for m in context.messages if isinstance(m, AssistantMessage))
    assert all("half" not in str(m.content) for m in context.messages if isinstance(m, AssistantMessage))
