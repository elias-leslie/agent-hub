from __future__ import annotations

import json

import pytest

from app.llm.providers.openai_codex_responses import _input_from_context, _raise_codex_http_error
from app.llm.types import AssistantMessage, Context, TextContent, ToolCall, ToolResultMessage, Usage
from app.services.llm_errors import AuthenticationError, ProviderError, RateLimitError


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
