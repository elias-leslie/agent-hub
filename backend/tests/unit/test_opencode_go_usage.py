"""OpenCode Go quota: parsing, request headers, failure handling and caching."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.services.subscription_accounting import opencode_go

_REAL_CLIENT = httpx.AsyncClient
KEY = "sk-test-opencode-secret"
GOOD = {
    "usage": {
        "rolling": {"status": "ok", "percent": 12, "resetsAt": "2026-10-23T18:59:20.000Z"},
        "weekly": {"status": "ok", "percent": 40, "resetsAt": "2026-10-27T00:00:00.000Z"},
        "monthly": {"status": "rate-limited", "percent": 100, "resetsAt": "2026-11-12T08:00:00.000Z"},
    }
}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(opencode_go, "get_env_api_key", lambda provider: KEY)
    opencode_go.clear_cache()


def _mock(monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(
        opencode_go.httpx, "AsyncClient", lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(respond), **kw)
    )
    return seen


def test_parse_reads_three_windows() -> None:
    windows = opencode_go.parse_usage(GOOD)
    assert windows is not None
    assert [(w["key"], w["label"], w["status"], w["percent"]) for w in windows] == [
        ("rolling", "5 hours", "ok", 12),
        ("weekly", "Week", "ok", 40),
        ("monthly", "Month", "rate-limited", 100),
    ]
    assert windows[0]["resets_at"] == "2026-10-23T18:59:20+00:00"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"usage": []},
        {"usage": {"rolling": {}}},
        {"usage": {**GOOD["usage"], "weekly": {"status": "ok", "percent": "40", "resetsAt": None}}},
        {"usage": {**GOOD["usage"], "weekly": {"status": "ok", "percent": 1, "resetsAt": "not a date"}}},
        {"usage": {k: v for k, v in GOOD["usage"].items() if k != "monthly"}},
    ],
)
def test_parse_rejects_malformed(payload: Any) -> None:
    assert opencode_go.parse_usage(payload) is None


@pytest.mark.asyncio
async def test_ok_response_and_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _mock(monkeypatch, lambda r: httpx.Response(200, json=GOOD))
    result = await opencode_go.get_usage()
    assert result["state"] == "ok" and len(result["windows"]) == 3
    headers = seen[0].headers
    assert headers["authorization"] == f"Bearer {KEY}"
    assert headers["user-agent"].startswith("agent-hub/")
    uuid.UUID(headers["x-opencode-session"])
    assert KEY not in repr(result)


@pytest.mark.asyncio
async def test_session_id_is_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    first = opencode_go.install_session_id()
    assert opencode_go.install_session_id() == first
    assert opencode_go.session_id_file().read_text().strip() == first


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 500, 502])
async def test_http_failures_are_unavailable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, status: int
) -> None:
    _mock(monkeypatch, lambda r: httpx.Response(status, text=f"nope {KEY}"))
    with caplog.at_level(logging.DEBUG):
        result = await opencode_go.get_usage()
    assert result["state"] == "unavailable" and result["windows"] == [] and result["reason"]
    assert KEY not in repr(result) and KEY not in caplog.text


@pytest.mark.asyncio
async def test_malformed_and_non_json_are_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock(monkeypatch, lambda r: httpx.Response(200, json={"usage": {"rolling": 3}}))
    assert (await opencode_go.get_usage())["state"] == "unavailable"
    opencode_go.clear_cache()
    _mock(monkeypatch, lambda r: httpx.Response(200, text="<html>"))
    assert (await opencode_go.get_usage())["state"] == "unavailable"


@pytest.mark.asyncio
async def test_network_error_is_unavailable_without_leaking_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect with {KEY}")

    _mock(monkeypatch, boom)
    with caplog.at_level(logging.DEBUG):
        result = await opencode_go.get_usage()
    assert result["state"] == "unavailable"
    assert KEY not in repr(result) and KEY not in caplog.text


@pytest.mark.asyncio
async def test_missing_key_is_not_configured_and_makes_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(opencode_go, "get_env_api_key", lambda provider: None)
    seen = _mock(monkeypatch, lambda r: httpx.Response(200, json=GOOD))
    result = await opencode_go.get_usage()
    assert result["state"] == "not_configured" and not seen


@pytest.mark.asyncio
async def test_results_are_cached_until_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _mock(monkeypatch, lambda r: httpx.Response(200, json=GOOD))
    first = await opencode_go.get_usage()
    assert await opencode_go.get_usage() is first and len(seen) == 1
    monkeypatch.setattr(opencode_go.settings, "opencode_go_usage_cache_seconds", 0.0)
    await opencode_go.get_usage()
    assert len(seen) == 2
