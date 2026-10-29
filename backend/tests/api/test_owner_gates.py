"""Credential, API-key, capture-stream and event-socket routes need the owner principal."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.core.access_identity import require_owner
from app.main import app

REGISTERED_CLIENT = {"X-Client-Id": "some-client", "X-Request-Source": "tests"}
HTTP_ROUTES = [
    ("POST", "/api/api-keys/1/rotate"),
    ("POST", "/api/api-keys"),
    ("PUT", "/api/credentials/1"),
    ("GET", "/api/credentials"),
    ("GET", "/api/lab-credentials"),
    ("POST", "/api/lab-credentials"),
    ("PUT", "/api/lab-credentials/neri-local/viewer"),
    ("PATCH", "/api/lab-credentials/neri-local/viewer"),
    ("DELETE", "/api/lab-credentials/neri-local/viewer"),
    ("GET", "/api/memory/capture/stream"),
]


async def _call(method: str, path: str, peer: str, headers: dict[str, str]):
    transport = ASGITransport(app=app, client=(peer, 50000))
    async with AsyncClient(transport=transport, base_url="http://localhost:8003") as client:
        return await client.request(method, path, headers=headers, json={} if method != "GET" else None)


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), HTTP_ROUTES)
@pytest.mark.parametrize("peer", ["10.20.0.9", "8.8.4.4"])
async def test_non_owner_with_registered_client_id_is_refused(method: str, path: str, peer: str) -> None:
    response = await _call(method, path, peer, REGISTERED_CLIENT)
    assert response.status_code in (401, 403)
    assert response.status_code != 200


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), HTTP_ROUTES)
async def test_loopback_flag_off_refuses_agent_with_registered_client_id(
    method: str, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "agent_hub_loopback_is_owner", False)
    response = await _call(method, path, "127.0.0.1", REGISTERED_CLIENT)
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_owner_dependency_admits_owner_token_and_loopback_and_refuses_others(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gated = FastAPI()

    @gated.get("/x", dependencies=[Depends(require_owner)])
    async def _x() -> dict[str, bool]:
        return {"ok": True}

    async def get(peer: str, headers: dict[str, str] | None = None) -> int:
        transport = ASGITransport(app=gated, client=(peer, 50000))
        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            return (await client.get("/x", headers=headers)).status_code

    assert await get("127.0.0.1") == 200
    assert await get("10.20.0.9") == 403
    monkeypatch.setattr(settings, "agent_hub_loopback_is_owner", False)
    token = tmp_path / "owner-token"
    token.write_text("s3cret\n")
    monkeypatch.setattr(settings, "agent_hub_owner_token_file", str(token))
    assert await get("127.0.0.1") == 403
    assert await get("127.0.0.1", {"X-Agent-Hub-Owner-Token": "wrong"}) == 403
    assert await get("127.0.0.1", {"X-Agent-Hub-Owner-Token": "s3cret"}) == 200


def test_events_socket_refused_for_non_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "agent_hub_loopback_is_owner", False)
    with TestClient(app) as client, pytest.raises(WebSocketDisconnect) as exc, client.websocket_connect("/api/events"):
        pass
    assert exc.value.code == 1008


def test_events_socket_accepts_loopback_owner() -> None:
    with TestClient(app, client=("127.0.0.1", 50000)) as client, client.websocket_connect("/api/events") as ws:
        ws.send_json({"type": "bogus"})
        assert ws.receive_json()["type"] == "error"
