"""Transport routes bind application and owner without exposing subscription keys."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.api.push import router
from app.db import get_db


@pytest.mark.asyncio
async def test_scoped_routes_require_verified_service_and_return_no_keys() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: SimpleNamespace()

    @app.middleware("http")
    async def identified_client(request: Request, call_next):
        request.state.client_id = request.headers.get("X-Client-Id")
        return await call_next(request)

    registered = {"id": "neri-client", "status": "active", "allowed_projects": '["neri"]'}
    saved = {"id": "fixture", "application_id": "neri", "owner_id": "neri-client"}
    headers = {"X-Client-Id": "neri-client", "X-Agent-Hub-Internal": "agent-hub-internal-v1"}
    subscription = {"endpoint": "https://push.invalid/fixture", "expirationTime": None,
                    "keys": {"p256dh": "fixture-key", "auth": "fixture-auth"}, "application_id": "neri"}
    with (
        patch("app.middleware.access_control_auth.get_cached_client", AsyncMock(return_value=registered)),
        patch("app.services.push_scope.get_cached_client", AsyncMock(return_value=registered)),
        patch("app.api.push.push_service.save_subscription", AsyncMock(return_value=saved)) as save,
        patch("app.api.push.push_service.delete_subscription", AsyncMock(return_value=True)) as delete,
        patch("app.api.push.push_service.send_push", AsyncMock(return_value=0)) as send,
    ):
        async with AsyncClient(transport=ASGITransport(app), base_url="http://fixture") as client:
            denied = await client.post("/api/push/subscriptions", json=subscription, headers={"X-Client-Id": "neri-client"})
            wrong_app = await client.post("/api/push/subscriptions", json={**subscription, "application_id": "summitflow"}, headers=headers)
            forged_owner = await client.post("/api/push/subscriptions", json={**subscription, "owner_id": "someone-else"}, headers=headers)
            response = await client.post("/api/push/subscriptions", json=subscription, headers=headers)
            delivery = await client.post("/api/push/send", json={"title": "Fixture", "body": "Transport only", "application_id": "neri", "project_id": "unrelated-label"}, headers=headers)
            removal = await client.request("DELETE", "/api/push/subscriptions", json={"endpoint": subscription["endpoint"], "application_id": "neri"}, headers=headers)
    assert (denied.status_code, wrong_app.status_code, forged_owner.status_code) == (401, 403, 422)
    assert response.status_code == 200
    assert response.json() == {"status": "subscribed", **saved, "owner_kind": "registered_service_client"}
    assert "fixture-key" not in response.text and "fixture-auth" not in response.text
    assert "https://push.invalid" not in response.text
    save.assert_awaited_once()
    assert save.call_args.kwargs["scope"].owner_id == "neri-client"
    assert removal.status_code == 200
    assert delete.call_args.kwargs["scope"].application_id == "neri"
    assert delivery.json()["delivered"] == 0
    assert delivery.json()["legacy_compatibility"] is False
    assert send.call_args.kwargs["scope"].application_id == "neri"
    assert send.call_args.kwargs["payload"]["project_id"] == "unrelated-label"
