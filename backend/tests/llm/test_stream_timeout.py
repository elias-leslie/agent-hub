"""Every model transport uses the one configured read bound, and a firing is named in the request record."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from openai import AsyncOpenAI

from app.config import settings
from app.llm.model_resolver import resolve_llm_model
from app.llm.providers import anthropic, openai_codex_responses, openai_completions
from app.llm.tool_loop import _close_metrics
from app.llm.types import Context, UserMessage
from app.llm.utils.outcomes import outcome_of
from app.llm.utils.request_metrics import request_metrics_of
from app.llm.utils.stream_timeout import IDLE_TIMEOUT_PREFIX, stream_timeout


def test_the_bound_is_the_setting_and_a_request_may_set_its_own() -> None:
    timeout = stream_timeout()
    assert isinstance(timeout, httpx.Timeout) and timeout.read == settings.llm_stream_read_timeout_s == 300.0
    assert timeout.connect == 30.0
    own = stream_timeout(5_000)
    assert isinstance(own, httpx.Timeout)
    assert (own.read, own.connect) == (5.0, 5.0)


def test_openai_sdk_client_carries_the_bound_not_the_sdk_default() -> None:
    model = resolve_llm_model("opencode-go/deepseek-v4.1-flash", "opencode-go")
    client = openai_completions.create_client(model, "key", None, None, openai_completions._get_compat(model))
    assert isinstance(client.timeout, httpx.Timeout) and client.timeout.read == settings.llm_stream_read_timeout_s


def test_loopback_openai_client_carries_the_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "local_openai_base_url", "http://127.0.0.1:11434/v1")
    model = resolve_llm_model("local/qwen3.8-27b-gsq-rco-iq3_s", "local")
    client = openai_completions.create_client(model, "key", None, None, openai_completions._get_compat(model))
    assert isinstance(client.timeout, httpx.Timeout)
    assert client.timeout.read == settings.llm_stream_read_timeout_s
    assert client._client.timeout.read == settings.llm_stream_read_timeout_s


def test_anthropic_client_carries_the_bound() -> None:
    model = resolve_llm_model("claude-sonnet-5-5", "anthropic")
    client = anthropic.create_client(model, "key", False, False, None, None)
    assert isinstance(client.timeout, httpx.Timeout)
    assert client.timeout.read == settings.llm_stream_read_timeout_s


@pytest.mark.asyncio
async def test_codex_read_timeout_is_named_interrupted_and_in_the_request_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    model = resolve_llm_model("codex/gpt-6.1-sol", "codex")

    @asynccontextmanager
    async def authenticated_response(*_args):
        yield SimpleNamespace(status_code=200)

    async def silent(_response):
        raise httpx.ReadTimeout("")
        yield  # pragma: no cover

    monkeypatch.setattr(openai_codex_responses, "_authenticated_response", authenticated_response)
    monkeypatch.setattr(openai_codex_responses, "_parse_sse_lines", silent)
    result = await openai_codex_responses.openai_codex_responses_provider.stream_simple(
        model, Context(messages=[])
    ).result()

    assert result.stop_reason == "error" and (result.error_message or "").startswith(IDLE_TIMEOUT_PREFIX)
    outcome = outcome_of(result)
    assert outcome is not None and outcome.kind == "interrupted"
    metrics = request_metrics_of(result) or {}
    assert metrics["outcome"].startswith(IDLE_TIMEOUT_PREFIX) and "300s" in metrics["outcome"]


@pytest.mark.asyncio
async def test_openai_compatible_read_timeout_is_named_interrupted_and_in_the_request_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "local_openai_base_url", "http://127.0.0.1:11434/v1")
    model = resolve_llm_model("local/qwen3.8-27b-gsq-rco-iq3_s", "local")

    def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("silent", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
        client = AsyncOpenAI(api_key="test", base_url=model.base_url, http_client=http_client, max_retries=0)
        monkeypatch.setattr(openai_completions, "create_client", lambda *args: client)
        stream = openai_completions.stream_openai_completions(
            model, Context(messages=[UserMessage(content="hi", timestamp=1)]), None
        )
        result = await stream.result()

    assert result.stop_reason == "error" and (result.error_message or "").startswith(IDLE_TIMEOUT_PREFIX)
    outcome = outcome_of(result)
    assert outcome is not None and outcome.kind == "interrupted"
    _close_metrics(result, 0.0, [])  # what run_turn records for a provider that keeps no metrics of its own
    assert (request_metrics_of(result) or {})["outcome"].startswith(IDLE_TIMEOUT_PREFIX)
