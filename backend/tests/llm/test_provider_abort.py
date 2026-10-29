"""An abort signal closes the provider's HTTP request at once, even while the model sends nothing."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator

import httpx
import pytest
from openai import AsyncOpenAI

from app.config import settings
from app.llm.model_resolver import resolve_llm_model
from app.llm.providers import openai_completions
from app.llm.providers.openai_completions import OpenAICompletionsOptions
from app.llm.types import Context, UserMessage


async def test_signal_closes_a_silent_openai_compatible_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "local_openai_base_url", "http://127.0.0.1:11434/v1")
    model = resolve_llm_model("local/qwen3.8-27b-gsq-rco-iq3_s", "local")
    first = {
        "id": "c", "object": "chat.completion.chunk", "created": 1, "model": model.id,
        "choices": [{"index": 0, "delta": {"reasoning_content": "hm"}, "finish_reason": None}],
    }
    body_closed = asyncio.Event()

    async def body() -> AsyncIterator[bytes]:
        try:
            yield f"data: {json.dumps(first)}\n\n".encode()
            await asyncio.Event().wait()  # the model goes quiet; nothing more is ever sent
        finally:
            body_closed.set()

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body())

    signal = asyncio.Event()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
        client = AsyncOpenAI(api_key="test", base_url=model.base_url, http_client=http_client)
        monkeypatch.setattr(openai_completions, "create_client", lambda *args: client)
        stream = openai_completions.stream_openai_completions(
            model,
            Context(messages=[UserMessage(content="hi", timestamp=1)]),
            OpenAICompletionsOptions(signal=signal),
        )
        events = stream.__aiter__()
        assert (await asyncio.wait_for(events.__anext__(), 2)).type == "start"
        assert (await asyncio.wait_for(events.__anext__(), 2)).type == "thinking_start"
        started = time.monotonic()
        signal.set()
        result = await asyncio.wait_for(stream.result(), 2)

    assert time.monotonic() - started < 1.0
    assert result.stop_reason == "aborted"
    assert body_closed.is_set(), "the HTTP response body was left open"
