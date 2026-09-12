"""Verified service identity and explicit legacy compatibility, without pushes."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.services.push_scope import application_for_client, resolve_push_scope


def request(*, verified: bool = True, client_id: str = "fixture-client") -> Request:
    headers = [(b"x-client-id", client_id.encode())]
    if verified:
        headers.append((b"x-agent-hub-internal", b"agent-hub-internal-v1"))
    value = Request({"type": "http", "headers": headers})
    value.state.client_id = client_id
    return value


@pytest.mark.asyncio
async def test_verified_application_and_owner_are_server_bound() -> None:
    client = {"id": "fixture-client", "status": "active", "allowed_projects": '["neri"]'}
    with patch("app.middleware.access_control_auth.get_cached_client", AsyncMock(return_value=client)):
        scope = await resolve_push_scope(request(), "neri")
        assert scope.application_id == "neri"
        assert scope.owner_id == "fixture-client"
        assert not scope.include_legacy
        with pytest.raises(HTTPException) as raised:
            await resolve_push_scope(request(), "summitflow")
        assert raised.value.status_code == 403


@pytest.mark.asyncio
async def test_identified_neri_is_not_authenticated() -> None:
    client = {"id": "fixture-client", "status": "active", "allowed_projects": '["neri"]'}
    with (
        patch("app.services.push_scope.get_cached_client", AsyncMock(return_value=client)),
        pytest.raises(HTTPException) as raised,
    ):
        await resolve_push_scope(request(verified=False), "neri")
    assert raised.value.status_code == 401


@pytest.mark.asyncio
async def test_legacy_summitflow_cannot_claim_another_application() -> None:
    client = {"id": "summitflow", "status": "active", "allowed_projects": '["summitflow", "neri"]'}
    with patch("app.services.push_scope.get_cached_client", AsyncMock(return_value=client)):
        scope = await resolve_push_scope(request(verified=False, client_id="summitflow"), None)
        assert scope.application_id == "summitflow"
        assert scope.include_legacy
        with pytest.raises(HTTPException) as raised:
            await resolve_push_scope(request(verified=False, client_id="summitflow"), "neri")
    assert raised.value.status_code == 401


@pytest.mark.asyncio
async def test_invalid_service_secret_cannot_fall_back_to_legacy_summitflow() -> None:
    value = Request({"type": "http", "headers": [
        (b"x-client-id", b"summitflow"), (b"x-agent-hub-internal", b"invalid-fixture-secret"),
    ]})
    value.state.client_id = "summitflow"
    with pytest.raises(HTTPException) as raised:
        await resolve_push_scope(value, None)
    assert raised.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("client", [None, {"id": "fixture-client", "status": "suspended"}])
async def test_unknown_or_inactive_verified_client_is_denied(client) -> None:
    with (
        patch("app.middleware.access_control_auth.get_cached_client", AsyncMock(return_value=client)),
        pytest.raises(HTTPException) as raised,
    ):
        await resolve_push_scope(request(), "neri")
    assert raised.value.status_code == 403


@pytest.mark.parametrize("projects", [None, "[]", '["neri", "other"]', '{"neri":true}', '"neri"'])
def test_broad_or_malformed_project_access_does_not_select_push_application(projects) -> None:
    with pytest.raises(HTTPException) as raised:
        application_for_client({"id": "fixture-client", "allowed_projects": projects})
    assert raised.value.status_code == 403
