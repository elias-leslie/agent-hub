"""Each model request's liveness record and its retries are stored as session events."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.api.complete.request_metrics import (
    MODEL_REQUEST_TOOL,
    model_request_record,
    store_model_requests,
)
from app.llm.types import AssistantMessage, Usage
from app.llm.utils.request_metrics import record_request_metrics


def _message(**metrics) -> AssistantMessage:
    message = AssistantMessage(content=[], api="x", provider="codex", model="gpt-6.1-sol", usage=Usage(), stop_reason="stop", timestamp=0)
    if metrics:
        record_request_metrics(message, **metrics)
    return message


def test_a_message_without_metrics_has_no_record() -> None:
    assert model_request_record(_message()) is None


def test_the_record_is_compact() -> None:
    record = model_request_record(
        _message(max_gap_s=31.0, keepalives=3, max_tool_args=120, outcome="ok", retries=0, retry_log=[], headers_s=None)
    )

    assert record == {
        "max_gap_s": 31.0, "keepalives": 3, "max_tool_args": 120, "outcome": "ok", "retries": 0,
        "model": "gpt-6.1-sol", "stop_reason": "stop",
    }


@pytest.mark.asyncio
async def test_a_request_with_retries_stores_one_retry_event_each_and_one_model_request_event() -> None:
    message = _message(
        max_gap_s=2.0, keepalives=0, outcome="ok", retries=2,
        retry_log=[{"reason": "dropped", "delay_s": 2.1}, {"reason": "stream ended before response.completed", "delay_s": 4.3}],
    )
    with patch("app.api.complete.request_metrics.store_event", new_callable=AsyncMock) as store:
        await store_model_requests(AsyncMock(), "sess", [message, _message()], model_used="gpt-6.1-sol", agent_id="coder")

    calls = [(c.args[2], c.kwargs.get("content"), c.kwargs.get("tool_name")) for c in store.await_args_list]
    assert [c[0] for c in calls] == ["error", "error", "tool_audit"]
    assert [c[1] for c in calls[:2]] == ["turn_retry: dropped", "turn_retry: stream ended before response.completed"]
    assert calls[2][2] == MODEL_REQUEST_TOOL
    stored = json.loads(calls[2][1])
    assert (stored["retries"], stored["outcome"], stored["max_gap_s"]) == (2, "ok", 2.0)
    assert "retry_log" not in stored


@pytest.mark.asyncio
async def test_a_compaction_is_stored_as_its_own_event_with_the_summarizers_cost_and_not_inside_the_model_request() -> None:
    compaction = {
        "status": "ok", "tokens_before": 9000, "tokens_after": 2500, "messages_summarized": 14,
        "summarizer_model": "gemini-3.1-flash-lite", "input_tokens": 8000, "output_tokens": 600, "cost_usd": 0.002,
    }
    message = _message(outcome="ok", retries=0, retry_log=[], compactions=[compaction])
    with (
        patch("app.api.complete.request_metrics.store_event", new_callable=AsyncMock) as store,
        patch("app.services.context_tracker.log_token_usage", new_callable=AsyncMock) as cost,
    ):
        await store_model_requests(AsyncMock(), "sess", [message], model_used="gpt-6.1-sol", agent_id="coder")

    assert [c.args[2] for c in store.await_args_list] == ["compaction", "tool_audit"]
    first = store.await_args_list[0].kwargs
    assert first["content"] == "Context compacted: 9000 -> 2500 tokens (14 messages summarized by gemini-3.1-flash-lite)"
    assert first["tool_output"] == compaction and first["usage"]["cost_usd"] == 0.002
    assert "compactions" not in json.loads(store.await_args_list[1].kwargs["content"])
    assert cost.await_args is not None and cost.await_args.args[2:5] == ("gemini-3.1-flash-lite", 8000, 600)
