"""Service authentication for private external-work verification."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.context_management import maintenance
from app.services.context_maintenance_actions import MaintenanceRequest
from app.services.runtime_context import CanonicalContextDeliveryRequest


def _request(internal_secret: str | None) -> Request:
    headers = [(b"x-client-id", b"summitflow")]
    if internal_secret is not None:
        headers.append((b"x-agent-hub-internal", internal_secret.encode()))
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/api/runtime-context/manage/maintenance",
        "headers": headers,
    })


def _payload() -> MaintenanceRequest:
    return MaintenanceRequest(
        action="verify_work",
        context=CanonicalContextDeliveryRequest(
            consumer_surface="agent_runtime",
            agent_slug="memory-curator",
            project_id="agent-hub",
        ),
        item_id="item-1",
        task_id="task-1",
        external_request_key="item-1:generation-2",
        external_payload_digest="sha256:payload",
        generation=2,
    )


@pytest.mark.asyncio
async def test_verify_work_route_accepts_bound_internal_service_client() -> None:
    client = {
        "id": "summitflow",
        "status": "active",
        "allowed_projects": '["summitflow", "agent-hub"]',
    }
    db = AsyncMock()
    result = {"verified": True}
    with (
        patch("app.middleware.access_control_paths.settings.internal_service_secret", "secret"),
        patch("app.middleware.access_control_auth.get_cached_client", AsyncMock(return_value=client)),
        patch("app.api.context_management.handle_maintenance", AsyncMock(return_value=result)) as handle,
    ):
        response = await maintenance(_payload(), _request("secret"), db)

    assert response == result
    handle.assert_awaited_once()
    assert handle.await_args is not None
    assert handle.await_args.kwargs["caller_service_client"] == client


@pytest.mark.asyncio
@pytest.mark.parametrize("secret", [None, "wrong"])
async def test_verify_work_route_rejects_missing_or_wrong_internal_secret(secret: str | None) -> None:
    db = AsyncMock()
    with (
        patch("app.middleware.access_control_paths.settings.internal_service_secret", "secret"),
        patch("app.middleware.access_control_auth.get_cached_client", AsyncMock()) as lookup,
        pytest.raises(HTTPException) as raised,
    ):
        await maintenance(_payload(), _request(secret), db)

    assert raised.value.status_code == 401
    lookup.assert_not_awaited()
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_verify_work_route_rejects_inactive_service_client() -> None:
    db = AsyncMock()
    with (
        patch("app.middleware.access_control_paths.settings.internal_service_secret", "secret"),
        patch(
            "app.middleware.access_control_auth.get_cached_client",
            AsyncMock(return_value={"id": "summitflow", "status": "inactive"}),
        ),
        pytest.raises(HTTPException) as raised,
    ):
        await maintenance(_payload(), _request("secret"), db)

    assert raised.value.status_code == 403
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_verify_work_route_rejects_service_without_agent_hub_project_access() -> None:
    client = {"id": "other-service", "status": "active", "allowed_projects": '["other"]'}
    db = AsyncMock()
    with (
        patch("app.middleware.access_control_paths.settings.internal_service_secret", "secret"),
        patch("app.middleware.access_control_auth.get_cached_client", AsyncMock(return_value=client)),
        patch("app.services.context_maintenance_actions.relevant_items", AsyncMock(return_value=[])),
        pytest.raises(HTTPException) as raised,
    ):
        await maintenance(_payload(), _request("secret"), db)

    assert raised.value.status_code == 404
    db.rollback.assert_awaited_once()
