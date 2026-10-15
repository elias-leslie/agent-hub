"""Other sites' pages cannot reach the backend: foreign Host (DNS rebinding) and foreign Origin on writes."""

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.middleware.access_control_paths import is_auth_bypass_path
from app.middleware.request_origin import RequestOriginMiddleware

OWN = "http://localhost:3003"


def _guarded() -> TestClient:
    inner = FastAPI()

    @inner.get("/r")
    async def read() -> dict[str, bool]:
        return {"ok": True}

    @inner.post("/w")
    async def write() -> dict[str, bool]:
        return {"ok": True}

    @inner.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_text("hi")
        await websocket.close()

    inner.add_middleware(RequestOriginMiddleware, trusted_hosts=["testserver", "::1"], allowed_origins=[OWN])
    return TestClient(inner)


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"origin": "https://evil.example", "content-type": "text/plain"}, 403),
        ({"origin": "null"}, 403),
        ({"origin": OWN}, 200),
        ({}, 200),
    ],
)
def test_writes_need_our_origin_or_none(headers: dict[str, str], status: int) -> None:
    response = _guarded().post("/w", headers=headers, content=b"{}")
    assert response.status_code == status
    if status == 403:
        assert response.json() == {"error": "origin_not_allowed"}


def test_cross_site_reads_pass_the_guard() -> None:
    assert _guarded().get("/r", headers={"origin": "https://evil.example"}).status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8003", "localhost.evil.example", ""])
def test_foreign_host_is_refused(host: str) -> None:
    response = _guarded().get("/r", headers={"host": host})
    assert response.status_code == 400
    assert response.json() == {"error": "host_not_allowed"}


def test_ipv6_loopback_host_is_accepted() -> None:
    assert _guarded().get("/r", headers={"host": "[::1]:8003"}).status_code == 200


def test_websocket_from_another_site_is_refused() -> None:
    client = _guarded()
    with pytest.raises(WebSocketDisconnect) as refused, client.websocket_connect(
        "/ws", headers={"origin": "https://evil.example"}
    ):
        pass
    assert refused.value.code == 1008
    with client.websocket_connect("/ws", headers={"origin": OWN}) as ws:
        assert ws.receive_text() == "hi"


async def test_app_refuses_foreign_host_and_origin() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/", headers={"host": "evil.example"})).status_code == 400
        refused = await client.post("/api/agents", headers={"origin": "https://evil.example"}, content="x")
        assert refused.status_code == 403
        assert (await client.get("/")).status_code == 200


def test_anonymous_agents_bypass_is_read_only() -> None:
    assert is_auth_bypass_path("/api/agents", "GET")
    assert is_auth_bypass_path("/api/agents/coder", "HEAD")
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert not is_auth_bypass_path("/api/agents/coder", method)
    assert is_auth_bypass_path("/api/models", "GET")


async def test_anonymous_agent_write_must_identify() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/agents", json={})
    assert response.status_code == 400
