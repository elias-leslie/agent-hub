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


def test_check_response_echoes_style_warnings_to_stderr(capsys) -> None:
    from agent_hub_st.memory_api import _check_response

    response = Mock(status_code=200)
    response.json.return_value = {"uuid": "u1", "style_warnings": ["padding: please"]}

    assert _check_response(response, "http://hub")["uuid"] == "u1"
    assert capsys.readouterr().err == "STYLE_WARN: padding: please\n"


def test_agent_hub_request_names_the_writing_session(monkeypatch) -> None:
    """Writes carry the agent's context delivery hash and Aico session so revisions name the writer."""
    monkeypatch.setenv("AGENT_HUB_CONTEXT_PREINJECTED_HASH", "9241d175")
    monkeypatch.setenv("AICO_SESSION_ID", "aico-widget-a36fa317")
    response = Mock(status_code=200)
    response.json.return_value = {"status": "ok"}
    client = Mock()
    client.post.return_value = response
    client_cm = Mock()
    client_cm.__enter__ = Mock(return_value=client)
    client_cm.__exit__ = Mock(return_value=False)

    with (
        patch("agent_hub_st.memory_api.load_credentials", return_value=("client-id", "st-memory")),
        patch("agent_hub_st.memory_api.get_agent_hub_url", return_value="http://localhost:8003/api"),
        patch("agent_hub_st.memory_api.httpx.Client", return_value=client_cm),
    ):
        agent_hub_request("POST", "/api/memory/add", json={}, tool_name="st memory save")

    headers = client.post.call_args.kwargs["headers"]
    assert headers["X-Context-Writer"] == "delivery=9241d175; session=aico-widget-a36fa317"


def test_agent_hub_request_sends_no_writer_outside_an_agent_session(monkeypatch) -> None:
    from agent_hub_st.memory_api import writer_context_header

    monkeypatch.delenv("AGENT_HUB_CONTEXT_PREINJECTED_HASH", raising=False)
    monkeypatch.delenv("AICO_SESSION_ID", raising=False)
    assert writer_context_header() is None
    monkeypatch.setenv("AICO_SESSION_ID", "aico-widget-1")
    assert writer_context_header() == "session=aico-widget-1"
