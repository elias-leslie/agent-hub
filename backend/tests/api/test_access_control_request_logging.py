"""request_logs correctness: heartbeat skipping, session attribution, client last_used_at."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.responses import Response

from app.middleware import access_control_auth
from app.middleware.access_control_handlers import (
    handle_auth_bypass,
    handle_identified_request,
    should_log_request,
)

_HEADERS = {"X-Client-Id": "client-1", "X-Request-Source": "pytest"}


def _request(*, state_session_id: str | None = None, path_params: dict[str, str] | None = None) -> MagicMock:
    request = MagicMock()
    request.headers = MagicMock()
    request.headers.get = MagicMock(side_effect=lambda key, default=None: _HEADERS.get(key, default))
    request.state = SimpleNamespace()
    if state_session_id is not None:
        request.state.session_id = state_session_id
    request.path_params = path_params or {}
    return request


async def _run_identified(path: str, status_code: int, request: MagicMock) -> AsyncMock:
    call_next = AsyncMock(return_value=Response(status_code=status_code))
    with (
        patch(
            "app.middleware.access_control_handlers.identify_client",
            new_callable=AsyncMock,
            return_value=({"id": "client-1"}, None),
        ),
        patch("app.middleware.access_control_handlers.set_identified_state"),
        patch("app.middleware.access_control_handlers.log_request", new_callable=AsyncMock) as log,
    ):
        response = await handle_identified_request(request, call_next, path, "POST", 0.0)
    assert response.status_code == status_code
    return log


@pytest.mark.parametrize(
    "path",
    ["/api/sessions/abc/heartbeat", "/api/session-ingestion/sessions/abc/heartbeat"],
)
def test_should_log_request_skips_only_successful_heartbeats(path: str) -> None:
    assert should_log_request(path, 200) is False
    assert should_log_request(path, 204) is False
    assert should_log_request(path, 404) is True
    assert should_log_request(path, 500) is True


def test_should_log_request_keeps_other_session_routes() -> None:
    assert should_log_request("/api/sessions/abc/events", 200) is True
    assert should_log_request("/api/sessions", 201) is True
    assert should_log_request("/api/complete", 200) is True


@pytest.mark.asyncio
async def test_successful_heartbeat_is_not_logged() -> None:
    log = await _run_identified("/api/sessions/abc/heartbeat", 200, _request())
    log.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_heartbeat_is_still_logged() -> None:
    request = _request(path_params={"session_id": "abc"})
    log = await _run_identified("/api/session-ingestion/sessions/abc/heartbeat", 404, request)
    log.assert_awaited_once()
    assert log.await_args_list[0].kwargs["status_code"] == 404
    assert log.await_args_list[0].kwargs["session_id"] == "abc"


@pytest.mark.asyncio
async def test_handler_set_session_id_is_logged() -> None:
    log = await _run_identified("/api/complete", 200, _request(state_session_id="sess-1"))
    assert log.await_args_list[0].kwargs["session_id"] == "sess-1"


@pytest.mark.asyncio
async def test_path_session_id_is_logged_when_handler_sets_none() -> None:
    request = _request(path_params={"session_id": "sess-path"})
    log = await _run_identified("/api/sessions/sess-path/events", 200, request)
    assert log.await_args_list[0].kwargs["session_id"] == "sess-path"


@pytest.mark.asyncio
async def test_auth_bypass_heartbeat_follows_same_rule() -> None:
    call_next = AsyncMock(return_value=Response(status_code=200))
    with patch("app.middleware.access_control_handlers.log_request", new_callable=AsyncMock) as log:
        await handle_auth_bypass(_request(), call_next, "/api/sessions/abc/heartbeat", "POST", 0.0)
    log.assert_not_awaited()


def _client_db(status: str) -> MagicMock:
    client = MagicMock()
    client.id = "client-1"
    client.status = status
    lookup = MagicMock()
    lookup.scalar_one_or_none.return_value = client
    db = MagicMock()
    db.execute = AsyncMock(return_value=lookup)
    db.commit = AsyncMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=None)
    return db


@pytest.mark.asyncio
async def test_cache_miss_stamps_last_used_at_once_per_ttl() -> None:
    access_control_auth.invalidate_client_cache("client-1")
    db = _client_db("active")
    try:
        with patch("app.middleware.access_control_auth.async_session", return_value=db):
            assert await access_control_auth.get_cached_client("client-1") is not None
            assert await access_control_auth.get_cached_client("client-1") is not None
    finally:
        access_control_auth.invalidate_client_cache("client-1")

    # One SELECT plus one UPDATE on the miss; the cache hit touches nothing.
    assert db.execute.await_count == 2
    update_stmt = str(db.execute.await_args_list[1].args[0])
    assert update_stmt.startswith("UPDATE clients")
    assert "last_used_at" in update_stmt
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cache_miss_does_not_stamp_inactive_client() -> None:
    access_control_auth.invalidate_client_cache("client-1")
    db = _client_db("suspended")
    try:
        with patch("app.middleware.access_control_auth.async_session", return_value=db):
            await access_control_auth.get_cached_client("client-1")
    finally:
        access_control_auth.invalidate_client_cache("client-1")

    assert db.execute.await_count == 1
    db.commit.assert_not_awaited()
