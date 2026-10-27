from __future__ import annotations

import json

import httpx
import pytest
from openai import AsyncOpenAI

from app.config import settings
from app.llm.model_resolver import resolve_llm_model
from app.llm.providers import openai_completions
from app.llm.providers.openai_completions import OpenAICompletionsOptions
from app.llm.types import (
    Context,
    TextContent,
    TextDeltaEvent,
    ThinkingContent,
    ThinkingDeltaEvent,
    UserMessage,
)
from app.llm.utils.outcomes import outcome_of


@pytest.mark.parametrize("reasoning_field", [None, "reasoning", "reasoning_content"])
async def test_qwen_completion_preserves_answer_and_separate_reasoning(
    monkeypatch: pytest.MonkeyPatch,
    reasoning_field: str | None,
) -> None:
    """Synthetic SDK stream coverage; these are not captured Ollama responses."""
    monkeypatch.setattr(settings, "local_openai_base_url", "http://127.0.0.1:11434/v1")
    model = resolve_llm_model("local/qwen3.8-27b-gsq-rco-iq3_s", "local")
    expected_effort = "low" if reasoning_field else "none"
    deltas = ([{reasoning_field: "Check the answer."}] if reasoning_field else []) + [
        {"content": "OK"},
    ]
    chunks = [
        {
            "id": "completion-test",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": model.id,
            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
        }
        for delta in deltas
    ]
    chunks.append(
        {
            "id": "completion-test",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": model.id,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
    )

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["reasoning_effort"] == expected_effort
        assert "chat_template_kwargs" not in body
        assert "reasoning_budget_tokens" not in body
        content = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=content + "data: [DONE]\n\n",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
        client = AsyncOpenAI(
            api_key="test",
            base_url=model.base_url,
            http_client=http_client,
        )
        monkeypatch.setattr(openai_completions, "create_client", lambda *args: client)
        stream = openai_completions.stream_openai_completions(
            model,
            Context(messages=[UserMessage(content="Reply with exactly: OK", timestamp=1)]),
            OpenAICompletionsOptions(reasoning_effort="low" if reasoning_field else None),
        )
        events = [event async for event in stream]
        result = await stream.result()

    assert result.stop_reason == "stop", result.error_message
    assert result.response_model == model.id
    assert [block.text for block in result.content if isinstance(block, TextContent)] == ["OK"]
    thinking = [block for block in result.content if isinstance(block, ThinkingContent)]
    assert [block.thinking for block in thinking] == (["Check the answer."] if reasoning_field else [])
    assert [block.thinking_signature for block in thinking] == ([reasoning_field] if reasoning_field else [])
    assert [event.delta for event in events if isinstance(event, TextDeltaEvent)] == ["OK"]
    assert [event.delta for event in events if isinstance(event, ThinkingDeltaEvent)] == (
        ["Check the answer."] if reasoning_field else []
    )
    assert events[-1].type == "done"


@pytest.mark.parametrize("finish_reason", ["content_filter", "length"])
async def test_content_filter_is_a_typed_refusal_and_keeps_the_served_model(
    monkeypatch: pytest.MonkeyPatch, finish_reason: str,
) -> None:
    """Synthetic SDK stream: an OpenAI-compatible route that filters its own output."""
    monkeypatch.setattr(settings, "local_openai_base_url", "http://127.0.0.1:11434/v1")
    model = resolve_llm_model("local/qwen3.8-27b-gsq-rco-iq3_s", "local")
    chunk = {
        "id": "completion-filter", "object": "chat.completion.chunk", "created": 1, "model": model.id,
        "choices": [{"index": 0, "delta": {"content": "x"}, "finish_reason": finish_reason}],
    }

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"},
            content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
        client = AsyncOpenAI(api_key="test", base_url=model.base_url, http_client=http_client)
        monkeypatch.setattr(openai_completions, "create_client", lambda *args: client)
        stream = openai_completions.stream_openai_completions(
            model, Context(messages=[UserMessage(content="hi", timestamp=1)]), OpenAICompletionsOptions(),
        )
        result = await stream.result()

    outcome = outcome_of(result)
    if finish_reason == "length":
        assert outcome is None
        return
    assert result.stop_reason == "error"
    assert outcome is not None
    assert (outcome.kind, outcome.category, outcome.served_model) == ("refused", "content_filter", model.id)
