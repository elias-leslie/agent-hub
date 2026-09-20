"""Tests for Agent Hub memory API error rendering."""

from __future__ import annotations

from unittest.mock import Mock, patch

import httpx
from agent_hub_st.memory_api import _format_error_payload, agent_hub_request


def test_format_error_payload_prefers_message_details_and_hint() -> None:
    rendered = _format_error_payload(
        {
            "error": "validation_error",
            "message": "Content validation failed",
            "details": [{"message": "Episode must start with a bold topic header like **Git Safety**:"}],
            "hint": "Use a compact topic header.",
        },
        "fallback",
    )

    assert rendered == (
        "Content validation failed | Episode must start with a bold topic header like **Git Safety**: | Use a compact topic header."
    )


def test_agent_hub_request_retries_connect_error_then_succeeds() -> None:
    response = Mock(status_code=200)
    response.json.return_value = {"status": "ok"}

    client = Mock()
    client.get.side_effect = [
        httpx.ConnectError("transient failure"),
        response,
    ]
    client_cm = Mock()
    client_cm.__enter__ = Mock(return_value=client)
    client_cm.__exit__ = Mock(return_value=False)

    with (
        patch("agent_hub_st.memory_api.load_credentials", return_value=("client-id", "st-memory")),
        patch("agent_hub_st.memory_api.get_agent_hub_url", return_value="http://localhost:8003/api"),
        patch("agent_hub_st.memory_api.httpx.Client", return_value=client_cm),
        patch("agent_hub_st.memory_api.time.sleep") as mock_sleep,
    ):
        result = agent_hub_request(
            "GET",
            "/api/memory/progressive-context",
            tool_name="st memory status",
            retries=3,
        )

    assert result == {"status": "ok"}
    assert client.get.call_count == 2
    mock_sleep.assert_called_once()
