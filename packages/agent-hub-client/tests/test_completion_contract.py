"""All sync/async callers share truthful completion response handling."""
from types import SimpleNamespace

import httpx
import pytest

from agent_hub._completion import build_completion_payload, handle_completion_response
from agent_hub.models import NativeContinuation
from agent_hub.exceptions import ServerError


def _response(**extra):
    return httpx.Response(200, json={"content": "", "model": "gemini-3.8-flash", "provider": "gemini", "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, "session_id": "test", **extra})


@pytest.mark.parametrize("reason", ["error", "aborted"])
def test_http_200_does_not_make_provider_failure_successful(reason):
    with pytest.raises(ServerError, match=reason):
        handle_completion_response(_response(finish_reason=reason), SimpleNamespace())


def test_actual_routing_evidence_is_retained():
    response = handle_completion_response(_response(content="ok", finish_reason="stop", fallback_used=True, model_used="gemini-3.8-flash", fallback_reason="primary unavailable", agent_used="chat"), SimpleNamespace())
    assert response.fallback_used is True
    assert response.model_used == "gemini-3.8-flash"
    assert response.fallback_reason == "primary unavailable"
    assert response.agent_used == "chat"


def test_native_continuation_payload_is_explicit_and_delta_only():
    payload = build_completion_payload(
        messages=[{"role": "user", "content": "new evidence only"}],
        project_id="neri",
        agent_slug="neri-hunter",
        session_id="session-1",
        use_memory=False,
        native_continuation=NativeContinuation(
            mode="delta",
            generation=1,
            request_id="request-2",
            expected_turn=1,
            context_version="evidence-11",
            role="hunter",
            controller_generation="controller-1",
            instruction_hash="a" * 64,
            tool_policy_hash="b" * 64,
            cyber_access_program="standard",
        ),
    )

    assert payload["messages"] == [{"role": "user", "content": "new evidence only"}]
    assert payload["native_continuation"]["mode"] == "delta"
    assert payload["native_continuation"]["expected_turn"] == 1
    assert payload["native_continuation"]["cyber_access_program"] == "standard"
