"""A dead Codex stream is cut off, typed as interrupted, and re-run instead of hanging."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.config import settings
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

STALL = "stall"  # keepalives forever, no real event
RUNAWAY = "runaway"  # argument deltas forever for one tool call

KEEPALIVE = {"type": "keepalive"}
TEXT = [{"type": "response.output_text.delta", "delta": "hi"}, {"type": "response.completed", "response": {}}]
TOOL_CALL = [
    {"type": "response.output_item.added", "item": {"type": "function_call", "call_id": "c1", "name": "bash"}},
    {"type": "response.function_call_arguments.delta", "call_id": "c1", "delta": '{"command":"ls"}'},
    {
        "type": "response.output_item.done",
        "item": {"type": "function_call", "call_id": "c1", "id": "fc_1", "name": "bash", "arguments": '{"command":"ls"}'},
    },
    {"type": "response.completed", "response": {}},
]
PARTIAL_THEN_STALL = [{"type": "response.output_text.delta", "delta": "half"}, STALL]


@pytest.fixture
def sse(monkeypatch: pytest.MonkeyPatch):
    """Script the SSE items of each request in order; returns the request counter."""
    monkeypatch.setattr(settings, "llm_stream_progress_timeout_s", 0.1)
    monkeypatch.setattr(settings, "llm_tool_args_max_chars", 100)
    monkeypatch.setattr(codex, "_retry_delay", lambda _attempt: 0)
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
                if item == STALL:
                    while True:
                        await asyncio.sleep(0.01)
                        yield KEEPALIVE
                elif item == RUNAWAY:
                    yield TOOL_CALL[0]
                    while True:
                        yield {"type": "response.function_call_arguments.delta", "call_id": "c1", "delta": "x" * 30}
                elif isinstance(item, BaseException):
                    raise item
                else:
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


@pytest.mark.asyncio
async def test_keepalives_do_not_reset_the_progress_clock(sse) -> None:
    calls = sse([KEEPALIVE, STALL])

    result, _ = await _complete(max_retries=0)

    assert (calls[0], result.stop_reason) == (1, "error")
    assert "no progress" in (result.error_message or "")
    assert _kind(result) == "interrupted"


@pytest.mark.asyncio
async def test_a_stall_before_output_is_resent_by_the_provider(sse) -> None:
    calls = sse([STALL], TEXT)

    result, _ = await _complete(max_retries=1)

    assert (calls[0], result.stop_reason) == (2, "stop")
    assert outcome_of(result) is None


@pytest.mark.asyncio
async def test_a_stall_after_text_is_an_interrupted_error(sse) -> None:
    calls = sse(PARTIAL_THEN_STALL, TEXT)

    result, _ = await _complete(max_retries=2)

    assert (calls[0], result.stop_reason) == (1, "error")
    assert _kind(result) == "interrupted"


@pytest.mark.asyncio
async def test_a_dropped_connection_is_interrupted(sse) -> None:
    sse([*TEXT[:1], httpx.RemoteProtocolError("dropped")])

    result, _ = await _complete()

    assert (result.stop_reason, result.error_message) == ("error", "dropped")
    assert _kind(result) == "interrupted"


@pytest.mark.asyncio
async def test_a_healthy_stream_with_keepalives_between_events_is_unaffected(sse, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_stream_progress_timeout_s", 0.15)

    async def paced(_response) -> AsyncIterator[dict]:
        for item in [*TEXT[:1], *TEXT[:1], *TEXT[:1], TEXT[1]]:  # 4 real events 0.08s apart: 0.32s total, over the 0.15s limit
            for _ in range(4):
                await asyncio.sleep(0.02)
                yield KEEPALIVE
            yield item

    sse(TEXT)
    monkeypatch.setattr(codex, "_parse_sse_lines", paced)

    result, _ = await _complete(max_retries=0)

    assert result.stop_reason == "stop" and outcome_of(result) is None
    assert [b.text for b in result.content if isinstance(b, TextContent)] == ["hihihi"]


@pytest.mark.asyncio
async def test_a_runaway_tool_call_is_cut_off_and_logged(sse, caplog: pytest.LogCaptureFixture) -> None:
    calls = sse([RUNAWAY])

    with caplog.at_level(logging.WARNING, logger=codex.logger.name):
        result, _ = await _complete(max_retries=0)

    assert calls[0] == 1 and result.stop_reason == "error"
    assert _kind(result) == "interrupted"
    assert not any(isinstance(b, ToolCall) for b in result.content)
    warning = next(r.getMessage() for r in caplog.records if "argument chars" in r.getMessage())
    assert "'bash'" in warning and "xxxx" in warning


async def _run_loop(options: SimpleStreamOptions | None = None) -> tuple[list, Context]:
    context = Context(messages=[UserMessage(content="go", timestamp=0)])

    async def run_tool(call: ToolCall) -> ToolResultMessage:
        return ToolResultMessage(tool_call_id=call.id, tool_name=call.name, content=[TextContent(text="ok")], is_error=False, timestamp=0)

    events = [e async for e in tool_loop.run(_model(), context, run_tool, options)]
    return events, context


@pytest.mark.asyncio
async def test_the_tool_loop_reruns_an_interrupted_turn_and_drops_the_partial(sse) -> None:
    calls = sse(PARTIAL_THEN_STALL, TOOL_CALL, TEXT)

    events, context = await _run_loop()

    assert calls[0] == 3
    retries = [e for e in events if isinstance(e, tool_loop.TurnRetry)]
    assert [(r.attempt, r.max_retries) for r in retries] == [(1, 2)]
    assert "no progress" in retries[0].reason
    kinds = [e.type for e in events]
    assert kinds.index("turn_retry") > kinds.index("text_delta")  # the partial was streamed, then voided
    assert "error" not in kinds
    assert [type(m).__name__ for m in context.messages] == ["UserMessage", "AssistantMessage", "ToolResultMessage", "AssistantMessage"]
    assert all(outcome_of(m) is None for m in context.messages if isinstance(m, AssistantMessage))
    assert all("half" not in str(m.content) for m in context.messages if isinstance(m, AssistantMessage))


@pytest.mark.asyncio
async def test_the_loop_surfaces_the_error_once_the_retry_budget_is_spent(sse) -> None:
    calls = sse([STALL], [STALL], [STALL])

    events, context = await _run_loop(SimpleStreamOptions(max_retries=1))

    assert calls[0] == 2  # the provider never retries on its own inside the loop
    assert [type(e).__name__ for e in events].count("TurnRetry") == 1
    error = events[-1]
    assert error.type == "error" and _kind(error.error) == "interrupted"
    assert _kind(context.messages[-1]) == "interrupted"
    assert [e.type for e in events].count("error") == 1


@pytest.mark.asyncio
async def test_a_runaway_turn_is_rerun_by_the_loop(sse) -> None:
    calls = sse([RUNAWAY], TEXT)

    events, context = await _run_loop()

    assert calls[0] == 2
    assert [type(e).__name__ for e in events].count("TurnRetry") == 1
    last = context.messages[-1]
    assert isinstance(last, AssistantMessage) and last.stop_reason == "stop"
