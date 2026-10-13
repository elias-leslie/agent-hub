"""The dashboard proxy decides on the real caller, not on its own loopback hop or Host."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.core import access_identity
from app.main import app


async def _me(headers: dict[str, str], peer: str = "127.0.0.1") -> tuple[int, dict]:
    transport = ASGITransport(app=app, client=(peer, 50000))
    async with AsyncClient(transport=transport, base_url="http://localhost:8003") as client:
        response = await client.get("/api/auth/me", headers=headers)
    return response.status_code, response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["1.1.1.1", "unknown", ""])
async def test_spoofed_local_host_from_a_non_lan_address_is_not_owner(address: str) -> None:
    status, body = await _me({
        "Host": "localhost",
        "X-Forwarded-Host": "localhost",
        "X-Forwarded-For": "127.0.0.1",
        "X-Agent-Hub-Client-Address": address,
    })
    assert status == 200
    assert body["is_owner"] is False


@pytest.mark.asyncio
async def test_direct_non_local_peer_is_not_owner_whatever_its_host() -> None:
    status, body = await _me({"Host": "localhost", "X-Forwarded-For": "127.0.0.1"}, peer="8.8.4.4")
    assert status == 200
    assert body["is_owner"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["127.0.0.1", "::1", "::ffff:127.0.0.1"])
async def test_loopback_clients_keep_owner_access(address: str) -> None:
    status, body = await _me({"Host": "agent.summitflow.dev", "X-Agent-Hub-Client-Address": address})
    assert status == 200
    assert body == {"email": None, "is_owner": True, "is_local_bypass": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["192.168.86.128", "192.168.86.234", "10.20.0.102", "::ffff:10.0.0.4", "192.168.87.20"])
async def test_lan_clients_without_access_are_not_owner(address: str) -> None:
    status, body = await _me({"Host": "agent.summitflow.dev", "X-Agent-Hub-Client-Address": address})
    assert status == 200
    assert body["is_owner"] is False and body["is_local_bypass"] is False


@pytest.mark.asyncio
async def test_direct_loopback_caller_without_proxy_header_is_owner() -> None:
    _, body = await _me({})
    assert body["is_owner"] is True


@pytest.mark.asyncio
async def test_verified_owner_assertion_is_owner_and_other_emails_are_not() -> None:
    with (
        patch.object(access_identity.settings, "agent_hub_owner_emails", "owner@example.com"),
        patch.object(access_identity, "_email_from_access_token", side_effect=["owner@example.com", "guest@example.com"]),
    ):
        _, owner = await _me({"Cf-Access-Jwt-Assertion": "t1", "X-Agent-Hub-Client-Address": "1.1.1.1"})
        _, guest = await _me({"Cf-Access-Jwt-Assertion": "t2", "X-Agent-Hub-Client-Address": "127.0.0.1"})
    assert owner["is_owner"] is True and owner["email"] == "owner@example.com"
    assert guest["is_owner"] is False


@pytest.mark.asyncio
async def test_access_cookie_is_verified_like_the_header() -> None:
    with patch.object(
        access_identity, "_email_from_access_token",
        side_effect=HTTPException(status_code=401, detail="Invalid Cloudflare Access token"),
    ):
        status, _ = await _me({"Cookie": "CF_Authorization=bad", "X-Agent-Hub-Client-Address": "127.0.0.1"})
    assert status == 401


def test_assertion_without_access_config_is_refused() -> None:
    with (
        patch.object(access_identity.settings, "cloudflare_access_team_domain", ""),
        pytest.raises(HTTPException) as exc,
    ):
        access_identity._email_from_access_token("token")
    assert exc.value.status_code == 503
