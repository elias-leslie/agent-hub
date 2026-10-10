"""Sampled request_logs telemetry for internal-header (dashboard UI) requests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from starlette.responses import StreamingResponse

from app.api import dashboard_stats
from app.middleware import access_control_ui_logging as ui_logging
from app.middleware.access_control import AccessControlMiddleware
from app.middleware.access_control_paths import INTERNAL_SERVICE_HEADER

_SECRET = "test-internal-secret"
_INTERNAL = {
    INTERNAL_SERVICE_HEADER: _SECRET,
    "X-Client-Id": "dash-client",
    "X-Request-Source": "agent-hub-dashboard",
}
_DASHBOARD_CLIENT = {"id": "dash-client", "display_name": "agent-hub-dashboard"}


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/admin/items/{item_id}")
    async def admin_item(item_id: str) -> dict[str, str]:
        return {"id": item_id}

    @app.get("/api/things/{thing_id}")
    async def thing(thing_id: str) -> dict[str, str]:
        return {"id": thing_id}

    @app.post("/api/complete")
    async def complete() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/api/things/{thing_id}/stream")
    async def thing_stream(thing_id: str) -> dict[str, str]:
        return {"id": thing_id}

    @app.get("/api/events")
    async def events() -> StreamingResponse:
        async def gen() -> AsyncIterator[bytes]:
            yield b"data: x\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    app.add_middleware(AccessControlMiddleware)
    return app


async def _drive(
    rate: float,
    calls: list[tuple[str, str]],
    headers: dict[str, str] | None = None,
    cached_client: dict[str, Any] | None = _DASHBOARD_CLIENT,
) -> list[dict[str, Any]]:
    """Run requests through the middleware and return logged request_logs kwargs."""
    log = AsyncMock()
    with (
        patch.object(ui_logging.settings, "internal_service_secret", _SECRET),
        patch.object(ui_logging.settings, "dashboard_ui_request_log_sample_rate", rate),
        patch.object(ui_logging, "log_request", log),
        patch.object(ui_logging, "get_cached_client", AsyncMock(return_value=cached_client)),
    ):
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for method, url in calls:
                response = await client.request(method, url, headers=headers or _INTERNAL)
                assert response.status_code == 200
        if ui_logging._pending_tasks:
            await asyncio.gather(*list(ui_logging._pending_tasks))
    return [dict(call.kwargs) for call in log.await_args_list]


@pytest.mark.asyncio
async def test_rate_zero_logs_nothing() -> None:
    rows = await _drive(0.0, [("GET", "/api/admin/items/1"), ("GET", "/api/things/2")])
    assert rows == []


@pytest.mark.asyncio
async def test_rate_one_logs_route_template_without_ids() -> None:
    rows = await _drive(1.0, [("GET", "/api/admin/items/abc-123"), ("GET", "/api/things/9")])

    assert [row["endpoint"] for row in rows] == ["/api/admin/items/{item_id}", "/api/things/{thing_id}"]
    for row in rows:
        assert row["request_source"] == "agent-hub-dashboard-ui"
        assert row["method"] == "GET"
        assert row["status_code"] == 200
        assert isinstance(row["latency_ms"], int)
        assert row["client_id"] == "dash-client"
        assert row["rejection_reason"] is None
        assert set(row) == {
            "client_id",
            "request_source",
            "endpoint",
            "method",
            "status_code",
            "rejection_reason",
            "latency_ms",
        }


@pytest.mark.asyncio
async def test_non_internal_requests_are_not_ui_logged() -> None:
    async def passthrough(request: Any, call_next: Any, *_: Any) -> Any:
        return await call_next(request)

    with patch("app.middleware.access_control.handle_identified_request", passthrough):
        rows = await _drive(1.0, [("GET", "/api/things/1")], headers={"X-Client-Id": "x"})
    assert rows == []


@pytest.mark.asyncio
async def test_excluded_and_streaming_paths_are_never_logged() -> None:
    rows = await _drive(
        1.0,
        [("POST", "/api/complete"), ("GET", "/api/things/1/stream"), ("GET", "/api/events")],
    )
    assert rows == []


@pytest.mark.parametrize(
    "path",
    [
        "/api/complete",
        "/api/dashboard/stats",
        "/api/health",
        "/api/providers/health",
        "/api/memory/capture/stream",
        "/api/persona/stream",
        "/_next/static/chunk.js",
        "/static/app.css",
    ],
)
def test_exclusion_list(path: str) -> None:
    assert ui_logging.is_ui_log_excluded(path) is True


@pytest.mark.parametrize("path", ["/api/admin/clients", "/api/runtime-context/preview", "/api/sessions/abc"])
def test_ui_paths_not_excluded(path: str) -> None:
    assert ui_logging.is_ui_log_excluded(path) is False


def test_should_sample_bounds_and_threshold() -> None:
    assert ui_logging.should_sample(0.0, rng=lambda: 0.0) is False
    assert ui_logging.should_sample(1.0, rng=lambda: 0.9999) is True
    assert ui_logging.should_sample(0.1, rng=lambda: 0.05) is True
    assert ui_logging.should_sample(0.1, rng=lambda: 0.5) is False


@pytest.mark.parametrize(("raw", "expected"), [(-1, 0.0), (2, 1.0), ("bad", 0.0), (float("nan"), 0.0), (0.25, 0.25)])
def test_sample_rate_is_clamped(raw: Any, expected: float) -> None:
    with patch.object(ui_logging.settings, "dashboard_ui_request_log_sample_rate", raw):
        assert ui_logging.ui_sample_rate() == expected


@pytest.mark.asyncio
async def test_db_error_is_swallowed_and_request_succeeds() -> None:
    log = AsyncMock(side_effect=RuntimeError("db down"))
    with (
        patch.object(ui_logging.settings, "internal_service_secret", _SECRET),
        patch.object(ui_logging.settings, "dashboard_ui_request_log_sample_rate", 1.0),
        patch.object(ui_logging, "log_request", log),
        patch.object(ui_logging, "get_cached_client", AsyncMock(side_effect=RuntimeError("db down"))),
    ):
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/admin/items/1", headers=_INTERNAL)
        assert response.status_code == 200
        results = await asyncio.gather(*list(ui_logging._pending_tasks), return_exceptions=True)
    assert all(result is None for result in results)


@pytest.mark.asyncio
async def test_real_log_writer_swallows_db_error() -> None:
    """The shared request_logs writer never raises on session failure."""
    with patch("app.middleware.access_control_logging.async_session", side_effect=RuntimeError("db down")):
        await ui_logging._write_ui_log(None, None, "/api/admin/items/{item_id}", "GET", 200, 3)


@pytest.mark.asyncio
async def test_unregistered_client_id_is_not_attributed() -> None:
    log = AsyncMock()
    with (
        patch.object(ui_logging, "log_request", log),
        patch.object(ui_logging, "get_cached_client", AsyncMock(return_value=None)),
    ):
        await ui_logging._write_ui_log("unknown", "summitflow", "/api/x", "GET", 200, 1)
    assert log.await_args is not None
    assert log.await_args.kwargs["client_id"] is None
    assert log.await_args.kwargs["request_source"] == "internal-service:summitflow"


@pytest.mark.asyncio
async def test_internal_service_caller_is_not_labelled_dashboard_ui() -> None:
    """Regression: SummitFlow native-sources calls carry the internal header but are not UI."""
    summitflow = {"id": "sf-client", "display_name": "summitflow"}
    headers = {INTERNAL_SERVICE_HEADER: _SECRET, "X-Client-Id": "sf-client", "X-Request-Source": "summitflow"}
    rows = await _drive(1.0, [("GET", "/api/things/1")], headers=headers, cached_client=summitflow)
    assert [row["request_source"] for row in rows] == ["internal-service:summitflow"]
    assert rows[0]["client_id"] == "sf-client"


@pytest.mark.parametrize(
    ("client", "header", "expected"),
    [
        ({"id": "d", "display_name": "agent-hub-dashboard"}, "agent-hub-dashboard", "agent-hub-dashboard-ui"),
        (None, "agent-hub-dashboard", "agent-hub-dashboard-ui"),
        ({"id": "s", "display_name": "summitflow"}, "agent-hub-dashboard", "internal-service:summitflow"),
        ({"id": "p", "display_name": "portfolio-ai"}, None, "internal-service:portfolio-ai"),
        (None, "custom-svc", "internal-service:custom-svc"),
        (None, None, "internal-service:unknown"),
        (None, "x" * 200, "internal-service:" + "x" * 83),
    ],
)
def test_internal_request_source(client: dict[str, Any] | None, header: str | None, expected: str) -> None:
    assert ui_logging.internal_request_source(client, header) == expected


@pytest.mark.asyncio
async def test_ui_rows_never_match_model_call_metrics() -> None:
    """Regression: UI rows must not enter dashboard model-call stats.

    Dashboard RequestMetrics count POST /api/complete rows; health and latency
    stats require a non-null model; agent metrics key on agent_slug. Drive every
    UI shape, including an internal POST /api/complete, and check none matches.
    """
    rows = await _drive(
        1.0,
        [("POST", "/api/complete"), ("GET", "/api/admin/items/1"), ("GET", "/api/things/2")],
    )
    assert rows, "rate 1 should log the non-excluded UI requests"
    for row in rows:
        assert not (
            row["endpoint"] == dashboard_stats.MODEL_CALL_ENDPOINT
            and row["method"] == dashboard_stats.MODEL_CALL_METHOD
        )
        assert row.get("model") is None
        assert row.get("agent_slug") is None
