"""The dashboard proxy decides on the real caller, not on its own loopback hop."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.core import access_identity
from app.main import app


async def _me(headers: dict[str, str]) -> tuple[int, dict]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:8003") as client:
        response = await client.get("/api/auth/me", headers=headers)
    return response.status_code, response.json()


@pytest.mark.asyncio
async def test_access_hostname_without_assertion_is_not_owner() -> None:
    status, body = await _me({"X-Forwarded-Host": "agent.summitflow.dev"})
    assert status == 200
    assert body["is_owner"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["localhost:3003", "127.0.0.1:3003", "192.168.86.128:3003"])
async def test_local_and_lan_hosts_keep_owner_access(host: str) -> None:
    status, body = await _me({"X-Forwarded-Host": host})
    assert status == 200
    assert body == {"email": None, "is_owner": True, "is_local_bypass": True}


@pytest.mark.asyncio
async def test_verified_owner_assertion_is_owner_and_other_emails_are_not() -> None:
    with (
        patch.object(access_identity.settings, "agent_hub_owner_emails", "owner@example.com"),
        patch.object(access_identity, "_email_from_access_token", side_effect=["owner@example.com", "guest@example.com"]),
    ):
        _, owner = await _me({"Cf-Access-Jwt-Assertion": "t1", "X-Forwarded-Host": "agent.summitflow.dev"})
        _, guest = await _me({"Cf-Access-Jwt-Assertion": "t2", "X-Forwarded-Host": "localhost"})
    assert owner["is_owner"] is True and owner["email"] == "owner@example.com"
    assert guest["is_owner"] is False


@pytest.mark.asyncio
async def test_access_cookie_is_verified_like_the_header() -> None:
    with patch.object(
        access_identity, "_email_from_access_token",
        side_effect=HTTPException(status_code=401, detail="Invalid Cloudflare Access token"),
    ):
        status, _ = await _me({"Cookie": "CF_Authorization=bad", "X-Forwarded-Host": "agent.summitflow.dev"})
    assert status == 401


def test_assertion_without_access_config_is_refused() -> None:
    with (
        patch.object(access_identity.settings, "cloudflare_access_team_domain", ""),
        pytest.raises(HTTPException) as exc,
    ):
        access_identity._email_from_access_token("token")
    assert exc.value.status_code == 503
