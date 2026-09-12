"""All sync/async callers share truthful completion response handling."""
from types import SimpleNamespace

import httpx
import pytest

from agent_hub._completion import handle_completion_response
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
