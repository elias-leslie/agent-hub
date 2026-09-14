"""Access-control tests for the project-scoped Neri local-worker routes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, Request

from app.api import neri_local_worker as api


def _request(
    *,
    client_id: str | None = "client-1",
    allowed_projects: object = '["security-research"]',
    internal: bool = False,
    include_policy: bool = True,
) -> Request:
    request = Request({"type": "http", "method": "GET", "path": "/"})
    request.state.is_internal = internal
    if client_id is not None:
        request.state.client_id = client_id
    if include_policy:
        request.state.allowed_projects = allowed_projects
    return request


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "http_request",
    [
        _request(client_id=None, include_policy=False),
        _request(allowed_projects=["security-research"]),
        _request(allowed_projects='["another-project"]'),
    ],
    ids=["missing-identity", "malformed-policy", "denied-project"],
)
async def test_status_fails_closed_for_unauthorized_identity(http_request: Request) -> None:
    with (
        patch.object(api, "get_neri_local_worker_status", new=AsyncMock()) as worker_status,
        pytest.raises(HTTPException) as raised,
    ):
        await api.status(http_request)

    assert raised.value.status_code == 403
    worker_status.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "http_request",
    [_request(), _request(client_id=None, include_policy=False, internal=True)],
    ids=["allowed-client", "verified-internal"],
)
async def test_status_allows_authorized_identity(http_request: Request) -> None:
    expected = SimpleNamespace(model_id="candidate")
    with patch.object(
        api, "get_neri_local_worker_status", new=AsyncMock(return_value=expected)
    ):
        assert await api.status(http_request) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["evaluate", "benchmark"])
async def test_mutating_routes_check_project_access_before_work(route: str) -> None:
    request = _request(allowed_projects='["another-project"]')
    handler = getattr(api, route)
    payload = SimpleNamespace()
    with pytest.raises(HTTPException) as raised:
        await handler(payload, request, AsyncMock())
    assert raised.value.status_code == 403
