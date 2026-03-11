"""Tests for the Agent Hub client payload builder."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "agent-hub-client"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))


def _build_completion_payload(*args, **kwargs):
    from agent_hub._completion import build_completion_payload

    return build_completion_payload(*args, **kwargs)


def test_build_completion_payload_includes_false_use_memory_flag() -> None:
    """SDK callers must be able to explicitly disable memory injection."""
    payload = _build_completion_payload(
        messages=[{"role": "user", "content": "Review AAPL"}],
        project_id="portfolio-ai",
        agent_slug="equity-analyst",
        use_memory=False,
    )

    assert payload["use_memory"] is False


def test_build_completion_payload_includes_true_use_memory_flag() -> None:
    """SDK callers should still be able to opt into memory injection."""
    payload = _build_completion_payload(
        messages=[{"role": "user", "content": "Review AAPL"}],
        project_id="portfolio-ai",
        agent_slug="equity-analyst",
        use_memory=True,
    )

    assert payload["use_memory"] is True


def test_build_completion_payload_includes_skip_cache_flag() -> None:
    """SDK callers must be able to bypass response-cache reads and writes."""
    payload = _build_completion_payload(
        messages=[{"role": "user", "content": "Review AAPL"}],
        project_id="portfolio-ai",
        agent_slug="equity-analyst",
        enable_caching=False,
        skip_cache=True,
    )

    assert payload["enable_caching"] is False
    assert payload["skip_cache"] is True


def test_build_completion_payload_includes_response_format_and_disable_fallbacks() -> None:
    payload = _build_completion_payload(
        messages=[{"role": "user", "content": "Review AAPL"}],
        project_id="portfolio-ai",
        agent_slug="equity-analyst",
        response_format={
            "type": "json_object",
            "schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}},
        },
        disable_agent_fallbacks=True,
    )

    assert payload["response_format"]["type"] == "json_object"
    assert payload["disable_agent_fallbacks"] is True


@pytest.mark.asyncio
async def test_async_client_complete_sends_skip_cache_header(monkeypatch) -> None:
    from agent_hub._async_client import AsyncAgentHubClient

    captured_headers: dict[str, str] = {}

    class FakeHttpClient:
        async def post(self, _path, json, headers, timeout):
            del json, timeout
            captured_headers.update(headers)
            return object()

    async def fake_get_client(self):
        return FakeHttpClient()

    def fake_handle_completion_response(_response, _client_instance):
        return SimpleNamespace(content="ok")

    monkeypatch.setattr(AsyncAgentHubClient, "_get_client", fake_get_client)
    monkeypatch.setattr(
        "agent_hub._async_client.handle_completion_response",
        fake_handle_completion_response,
    )

    async with AsyncAgentHubClient(
        base_url="http://localhost:8003",
        client_name="sdk-test",
    ) as client:
        await client.complete(
            messages=[{"role": "user", "content": "Review AAPL"}],
            project_id="portfolio-ai",
            agent_slug="equity-analyst",
            skip_cache=True,
        )

    assert captured_headers["X-Skip-Cache"] == "true"
