from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.api.typesafe_jev_schemas import (
    ChoiceQuestion,
    ScoreQuestion,
    SystemOneRequest,
)
from app.services.typesafe_jev import (
    TypeSafeJevError,
    _load_key_file,
    call_typesafe_jev,
)


def _request() -> SystemOneRequest:
    return SystemOneRequest(
        model="jev-1.13.0",
        state={"review": "sanitized context pair"},
        questions={
            "decision": {
                "type": "choice",
                "instructions": "Choose the supported assessment.",
                "criteria": {"supported": "Supported", "unsupported": "Unsupported"},
            }
        },
    )


@pytest.mark.asyncio
async def test_typed_client_sends_only_provider_fields_once() -> None:
    calls: list[dict[str, object]] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        calls.append(__import__("json").loads(request.content))
        return httpx.Response(
            200,
            headers={"x-typesafe-request-id": "provider-request-1"},
            json={
                "model": "jev-1.13.0",
                "answers": {
                    "decision": {
                        "type": "choice",
                        "choice": "supported",
                        "probabilities": {"supported": 0.8, "unsupported": 0.2},
                        "confidence": 0.8,
                    }
                },
                "usage": {"input_tokens": 321, "output_tokens": 0},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        response, provider_request_id = await call_typesafe_jev(
            _request(), api_key="test-key", http_client=client
        )

    assert provider_request_id == "provider-request-1"
    assert response.usage.input_tokens == 321
    assert len(calls) == 1
    assert set(calls[0]) == {"state", "model", "questions"}
    assert calls[0]["model"] == "jev-1.13.0"


@pytest.mark.asyncio
async def test_typed_client_fails_visibly_on_model_version_change() -> None:
    async def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"x-typesafe-request-id": "provider-request-2"},
            json={
                "model": "jev-1.14.0",
                "answers": {
                    "decision": {
                        "type": "choice",
                        "choice": "supported",
                        "probabilities": {"supported": 0.8, "unsupported": 0.2},
                        "confidence": 0.8,
                    }
                },
                "usage": {"input_tokens": 400, "output_tokens": 0},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(TypeSafeJevError) as caught:
            await call_typesafe_jev(_request(), api_key="test-key", http_client=client)

    assert caught.value.kind == "model_version_changed"
    assert caught.value.provider_request_id == "provider-request-2"
    assert caught.value.provider_response is not None
    assert caught.value.provider_response.usage.input_tokens == 400


@pytest.mark.parametrize("count", [1, 256])
def test_choice_cardinality_matches_provider_contract(count: int) -> None:
    with pytest.raises(ValidationError):
        ChoiceQuestion(type="choice", instructions="choose", criteria={str(i): i for i in range(count)})


@pytest.mark.parametrize("count", [1, 11])
def test_score_cardinality_matches_provider_contract(count: int) -> None:
    with pytest.raises(ValidationError):
        ScoreQuestion(type="score", instructions="score", criteria=list(range(count)))


def test_key_file_requires_owner_only_permissions(tmp_path: Path) -> None:
    key_file = tmp_path / "credentials.env"
    key_file.write_text("TYPESAFE_API_KEY=test-value\n", encoding="utf-8")
    key_file.chmod(0o600)
    assert _load_key_file(key_file) == "test-value"

    key_file.chmod(0o644)
    with pytest.raises(TypeSafeJevError, match="mode 0600"):
        _load_key_file(key_file)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,kind", [
    ("http", "provider_http_error"),
    ("malformed", "unsupported_output"),
    ("missing_answer", "unsupported_output"),
    ("excess_usage", "provider_contract_changed"),
])
async def test_generic_transport_retains_fail_visible_no_retry_behavior(failure, kind):
    calls = 0

    async def handle(_request):
        nonlocal calls
        calls += 1
        if failure == "http":
            return httpx.Response(503)
        if failure == "malformed":
            return httpx.Response(200, content=b"not-json")
        payload = {
            "model": "jev-1.13.0",
            "answers": {"decision": {"type": "choice", "choice": "supported", "probabilities": {"supported": 0.8, "unsupported": 0.2}, "confidence": 0.8}},
            "usage": {"input_tokens": 64001 if failure == "excess_usage" else 123, "output_tokens": 0},
        }
        if failure == "missing_answer":
            payload["answers"] = {}
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(TypeSafeJevError) as caught:
            await call_typesafe_jev(_request(), api_key="test-key", http_client=client)
    assert caught.value.kind == kind
    assert calls == 1
