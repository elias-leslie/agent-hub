"""Tests for the SummitFlow notification sink."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

import app.services.summitflow_notifications as sfn


def _install_transport(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    real_client = httpx.AsyncClient

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(sfn.httpx, "AsyncClient", factory)
    monkeypatch.setattr(sfn, "_read_summitflow_api_url", lambda: "http://sf.test/api")


async def test_posts_system_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "notif-1"})

    _install_transport(monkeypatch, handler)

    ok = await sfn.create_summitflow_notification(
        title="Host intervention required", message="disk", severity="critical", metadata={"a": 1}
    )

    assert ok is True
    assert len(seen) == 1
    assert seen[0].method == "POST"
    assert str(seen[0].url) == "http://sf.test/api/projects/agent-hub/notifications"
    assert json.loads(seen[0].content) == {
        "type": "system",
        "title": "Host intervention required",
        "message": "disk",
        "severity": "critical",
        "metadata": {"a": 1},
    }


async def test_http_failure_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_transport(monkeypatch, lambda request: httpx.Response(500))

    assert await sfn.create_summitflow_notification(title="t", message="m", severity="error") is False


async def test_missing_api_url_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sfn, "_read_summitflow_api_url", lambda: "")

    assert await sfn.create_summitflow_notification(title="t", message="m", severity="error") is False


async def test_spawn_runs_in_background(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    _install_transport(monkeypatch, handler)

    sfn.spawn_summitflow_notification(title="t", message="m", severity="error")
    await asyncio.gather(*list(sfn._background_tasks))

    assert len(seen) == 1
    assert not sfn._background_tasks


async def test_sends_dedupe_key_and_accepts_204(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    _install_transport(monkeypatch, handler)

    ok = await sfn.create_summitflow_notification(
        title="t", message="m", severity="error", dedupe_key="agent-run:failed"
    )

    assert ok is True
    assert json.loads(seen[0].content)["dedupe_key"] == "agent-run:failed"
