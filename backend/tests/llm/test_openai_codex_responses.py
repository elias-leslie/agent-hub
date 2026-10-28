from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.adapters.codex_auth import CodexCredentials
from app.config import settings
from app.llm.model_resolver import resolve_llm_model
from app.llm.providers import openai_codex_responses
from app.llm.providers.openai_codex_responses import (
    _authenticated_response,
    _input_from_context,
    _raise_codex_http_error,
)
from app.llm.types import (
    AssistantMessage,
    Context,
    TextContent,
    ToolCall,
    ToolResultMessage,
    Usage,
)
from app.llm.utils.outcomes import outcome_of
from app.services.llm_errors import AuthenticationError, ProviderError, RateLimitError


class _ResponseContext:
    def __init__(self, response) -> None:
        self.response = response
        self.exit_count = 0

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.exit_count += 1


def _assistant(content, *, response_id: str | None = None) -> AssistantMessage:
    return AssistantMessage(
        content=content,
        api="openai-codex-responses",
        provider="openai-codex",
        model="gpt-5.4",
        usage=Usage(),
        stop_reason="stop",
        timestamp=123,
        response_id=response_id,
    )


def test_replayed_assistant_text_never_uses_response_id_as_message_id() -> None:
    items, _instructions = _input_from_context(
        Context(
            messages=[
                _assistant(
                    [TextContent(text="done")],
                    response_id="resp_03a5f5ea998ae73a016a0524a7e0508191931dd30c385d52a7",
                )
            ]
        )
    )

    assert items[0]["type"] == "message"
    assert items[0]["id"] == "msg_123"


def test_replayed_assistant_text_uses_text_signature_message_id() -> None:
    signature = json.dumps({"v": 1, "id": "msg_keep", "phase": "final_answer"})

    items, _instructions = _input_from_context(
        Context(messages=[_assistant([TextContent(text="done", text_signature=signature)])])
    )

    assert items[0]["id"] == "msg_keep"
    assert items[0]["phase"] == "final_answer"


def test_replayed_codex_tool_ids_use_call_id_and_item_id_parts() -> None:
    items, _instructions = _input_from_context(
        Context(
            messages=[
                _assistant([ToolCall(id="call_123|fc_456", name="read_file", arguments={"path": "a.py"})]),
                ToolResultMessage(
                    tool_call_id="call_123|fc_456",
                    tool_name="read_file",
                    content=[TextContent(text="ok")],
                    is_error=False,
                    timestamp=124,
                ),
            ]
        )
    )

    assert items[0]["type"] == "function_call"
    assert items[0]["call_id"] == "call_123"
    assert items[0]["id"] == "fc_456"
    assert items[1]["type"] == "function_call_output"
    assert items[1]["call_id"] == "call_123"


def test_codex_http_429_maps_to_rate_limit_error() -> None:
    with pytest.raises(RateLimitError) as exc_info:
        _raise_codex_http_error(429, '{"error":"rate limit"}', {"Retry-After": "12"})
    assert exc_info.value.provider == "codex"
    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after == pytest.approx(12.0)


def test_codex_http_429_without_retry_after_still_maps() -> None:
    with pytest.raises(RateLimitError) as exc_info:
        _raise_codex_http_error(429, "rate limit exceeded", {})
    assert exc_info.value.provider == "codex"
    assert exc_info.value.retry_after is None


def test_codex_http_401_maps_to_authentication_error() -> None:
    with pytest.raises(AuthenticationError) as exc_info:
        _raise_codex_http_error(401, "unauthorized", {})
    assert exc_info.value.provider == "codex"
    assert exc_info.value.status_code == 401


def test_codex_http_403_maps_to_authentication_error() -> None:
    with pytest.raises(AuthenticationError):
        _raise_codex_http_error(403, "forbidden", {})


def test_codex_http_5xx_is_retriable_provider_error() -> None:
    with pytest.raises(ProviderError) as exc_info:
        _raise_codex_http_error(503, "service unavailable", {})
    err = exc_info.value
    assert not isinstance(err, (RateLimitError, AuthenticationError))
    assert err.provider == "codex"
    assert err.status_code == 503
    assert err.retriable is True


def test_codex_http_400_is_nonretriable_provider_error() -> None:
    with pytest.raises(ProviderError) as exc_info:
        _raise_codex_http_error(400, "bad request body", {})
    err = exc_info.value
    assert not isinstance(err, (RateLimitError, AuthenticationError))
    assert err.status_code == 400
    assert err.retriable is False


@pytest.mark.asyncio
async def test_pre_stream_401_refreshes_and_retries_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = CodexCredentials(
        access_token="initial-access",
        refresh_token="initial-refresh",
        account_id="account",
    )
    rotated = CodexCredentials(
        access_token="rotated-access",
        refresh_token="rotated-refresh",
        account_id="account",
    )
    store = SimpleNamespace(
        ensure_fresh=AsyncMock(return_value=initial),
        recover_after_auth_failure=AsyncMock(return_value=rotated),
    )
    unauthorized = MagicMock(status_code=401)
    unauthorized.aread = AsyncMock(return_value=b"unauthorized")
    success = MagicMock(status_code=200)
    first_context = _ResponseContext(unauthorized)
    second_context = _ResponseContext(success)
    client = MagicMock()
    client.stream.side_effect = [first_context, second_context]
    model = SimpleNamespace(base_url="https://example.test/codex")
    monkeypatch.setattr(openai_codex_responses, "_credential_store", store)

    async with _authenticated_response(client, model, {"stream": True}) as response:
        assert response is success

    assert client.stream.call_count == 2
    assert client.stream.call_args_list[0].kwargs["headers"]["Authorization"] == (
        "Bearer initial-access"
    )
    assert client.stream.call_args_list[1].kwargs["headers"]["Authorization"] == (
        "Bearer rotated-access"
    )
    unauthorized.aread.assert_awaited_once_with()
    store.recover_after_auth_failure.assert_awaited_once_with(
        "initial-access",
        "account",
    )
    assert first_context.exit_count == 1
    assert second_context.exit_count == 1


@pytest.mark.asyncio
async def test_repeated_pre_stream_401_does_not_refresh_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = CodexCredentials(
        access_token="initial-access",
        refresh_token="initial-refresh",
        account_id="account",
    )
    rotated = CodexCredentials(
        access_token="rotated-access",
        refresh_token="rotated-refresh",
        account_id="account",
    )
    store = SimpleNamespace(
        ensure_fresh=AsyncMock(return_value=initial),
        recover_after_auth_failure=AsyncMock(return_value=rotated),
    )
    responses = []
    contexts = []
    for _index in range(2):
        response = MagicMock(status_code=401)
        response.aread = AsyncMock(return_value=b"unauthorized")
        responses.append(response)
        contexts.append(_ResponseContext(response))
    client = MagicMock()
    client.stream.side_effect = contexts
    model = SimpleNamespace(base_url="https://example.test/codex")
    monkeypatch.setattr(openai_codex_responses, "_credential_store", store)

    async with _authenticated_response(client, model, {"stream": True}) as response:
        assert response is responses[1]

    assert client.stream.call_count == 2
    store.recover_after_auth_failure.assert_awaited_once_with(
        "initial-access",
        "account",
    )
    assert [context.exit_count for context in contexts] == [1, 1]


@pytest.mark.asyncio
async def test_pre_stream_403_does_not_attempt_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials = CodexCredentials(
        access_token="access",
        refresh_token="refresh",
        account_id="account",
    )
    store = SimpleNamespace(
        ensure_fresh=AsyncMock(return_value=credentials),
        recover_after_auth_failure=AsyncMock(),
    )
    forbidden = MagicMock(status_code=403)
    context = _ResponseContext(forbidden)
    client = MagicMock()
    client.stream.return_value = context
    model = SimpleNamespace(base_url="https://example.test/codex")
    monkeypatch.setattr(openai_codex_responses, "_credential_store", store)

    async with _authenticated_response(client, model, {"stream": True}) as response:
        assert response is forbidden

    store.recover_after_auth_failure.assert_not_awaited()
    assert context.exit_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reported_model", ["gpt-6.1-sol", None])
async def test_completion_preserves_observed_model_and_separates_cached_input(
    monkeypatch: pytest.MonkeyPatch, reported_model: str | None,
) -> None:
    model = resolve_llm_model("codex/gpt-6.1-sol", "codex")
    model = replace(model, cost=replace(model.cost, input=2.0, output=10.0, cache_read=0.1))

    @asynccontextmanager
    async def authenticated_response(*_args):
        yield SimpleNamespace(status_code=200)

    async def sse_lines(_response):
        yield {
            "type": "response.completed",
            "response": {
                "id": "resp-observed", "model": reported_model,
                "usage": {"input_tokens": 100, "output_tokens": 20,
                          "input_tokens_details": {"cached_tokens": 60}},
            },
        }

    monkeypatch.setattr(openai_codex_responses, "_authenticated_response", authenticated_response)
    monkeypatch.setattr(openai_codex_responses, "_parse_sse_lines", sse_lines)
    result = await openai_codex_responses.openai_codex_responses_provider.stream_simple(
        model, Context(messages=[]),
    ).result()

    assert result.model == "gpt-6.1-sol"
    assert result.response_model == reported_model
    assert result.response_id == "resp-observed"
    assert result.usage.input == 40
    assert result.usage.cache_read == 60
    assert result.usage.output == 20
    assert result.usage.total_tokens == 120
    assert result.usage.cost.total == pytest.approx((40 * 2 + 60 * 0.1 + 20 * 10) / 1_000_000)


def test_codex_stream_timeout_is_the_transport_bound_from_settings() -> None:
    timeout = openai_codex_responses._stream_timeout(None)
    assert timeout.read == settings.llm_stream_read_timeout_s == 300.0
    assert timeout.connect == 30.0


def test_codex_stream_timeout_honors_request_timeout() -> None:
    from app.llm.types import SimpleStreamOptions

    timeout = openai_codex_responses._stream_timeout(SimpleStreamOptions(timeout_ms=5_000))
    assert timeout.read == 5.0
    assert timeout.connect == 5.0


async def _run_events(monkeypatch: pytest.MonkeyPatch, events: list[dict]) -> AssistantMessage:
    model = resolve_llm_model("codex/gpt-6.1-sol", "codex")

    @asynccontextmanager
    async def authenticated_response(*_args):
        yield SimpleNamespace(status_code=200)

    async def sse_lines(_response):
        for event in events:
            yield event

    monkeypatch.setattr(openai_codex_responses, "_authenticated_response", authenticated_response)
    monkeypatch.setattr(openai_codex_responses, "_parse_sse_lines", sse_lines)
    return await openai_codex_responses.openai_codex_responses_provider.stream_simple(
        model, Context(messages=[]),
    ).result()


@pytest.mark.asyncio
@pytest.mark.parametrize("served", ["gpt-5.4", "gpt-6.1-sol"])
async def test_served_model_switch_is_typed_but_not_an_error(monkeypatch: pytest.MonkeyPatch, served: str) -> None:
    result = await _run_events(monkeypatch, [{"type": "response.completed", "response": {"model": served}}])

    assert result.stop_reason == "stop"
    outcome = outcome_of(result)
    if served == "gpt-6.1-sol":
        assert outcome is None
    else:
        assert outcome is not None
        assert (outcome.kind, outcome.requested_model, outcome.served_model) == ("substituted", "gpt-6.1-sol", served)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event", "category"),
    [
        ({"type": "response.failed", "response": {"error": {"code": "cyber_policy", "message": "flagged"}}}, "cyber"),
        ({"type": "error", "code": "bio_policy", "message": "flagged"}, "bio"),
        ({"type": "response.failed", "response": {"error": {"code": "misalignmentPolicyViolation", "message": "no"}}}, "misalignment"),
    ],
)
async def test_codex_safety_failures_are_typed_refusals(
    monkeypatch: pytest.MonkeyPatch, event: dict, category: str,
) -> None:
    result = await _run_events(monkeypatch, [event])

    assert result.stop_reason == "error"
    assert result.error_message
    outcome = outcome_of(result)
    assert outcome is not None
    assert (outcome.kind, outcome.category, outcome.requested_model) == ("refused", category, "gpt-6.1-sol")


@pytest.mark.asyncio
async def test_a_fatal_codex_failure_is_not_marked_interrupted(monkeypatch: pytest.MonkeyPatch) -> None:
    result = await _run_events(
        monkeypatch,
        [{"type": "response.failed", "response": {"error": {"code": "context_length_exceeded", "message": "too long"}}}],
    )

    assert (result.stop_reason, result.error_message, outcome_of(result)) == ("error", "too long", None)


@pytest.mark.asyncio
async def test_other_codex_failures_are_interrupted_so_the_turn_is_resent(monkeypatch: pytest.MonkeyPatch) -> None:
    result = await _run_events(
        monkeypatch, [{"type": "response.failed", "response": {"error": {"code": "server_error", "message": "boom"}}}],
    )

    outcome = outcome_of(result)
    assert (result.stop_reason, result.error_message) == ("error", "boom")
    assert outcome is not None and outcome.kind == "interrupted"
