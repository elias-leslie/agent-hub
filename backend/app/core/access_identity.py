"""Resolve the dashboard caller's real identity for the frontend proxy.

The Next.js proxy reaches this backend over loopback and adds the internal
service secret, so the backend cannot tell callers apart by connection. The
proxy forwards the caller's Cloudflare Access assertion, cookie and the client
address its server stamped from the TCP peer instead, and asks
``/api/auth/me`` whether that caller is an owner before it adds the secret.
Host and X-Forwarded-* headers are never trusted here.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from ipaddress import ip_address
from typing import Any

import jwt
from fastapi import HTTPException, Request
from jwt import PyJWKClient, PyJWTError

from app.config import settings

CLIENT_ADDRESS_HEADER = "X-Agent-Hub-Client-Address"


@dataclass(frozen=True)
class Caller:
    email: str | None
    is_owner: bool
    is_local_bypass: bool = False


def resolve_caller(request: Request) -> Caller:
    """Owner when Access proves an owner email, or for a loopback caller (this host) without Access."""
    token = (
        request.headers.get("Cf-Access-Jwt-Assertion", "").strip()
        or request.cookies.get("CF_Authorization", "").strip()
    )
    if token:
        email = _email_from_access_token(token)
        return Caller(email=email, is_owner=email in _owner_emails())
    if _is_local_address(_client_address(request)):
        return Caller(email=None, is_owner=True, is_local_bypass=True)
    return Caller(email=None, is_owner=False)


def _owner_emails() -> set[str]:
    return {e.strip().lower() for e in settings.agent_hub_owner_emails.split(",") if e.strip()}


def _client_address(request: Request) -> str:
    """The caller's network address, never derived from Host or X-Forwarded-*.

    The backend listens on loopback only. The dashboard proxy forwards the
    address its server stamped from the TCP peer; any other caller is judged
    by its own peer address.
    """
    forwarded = request.headers.get(CLIENT_ADDRESS_HEADER)
    if forwarded is not None:
        return forwarded.strip()
    return request.client.host if request.client else ""


def _is_local_address(value: str) -> bool:
    # Loopback only: processes on this host (cloudflared, Caddy for local
    # clients, agents). LAN peers are not trusted without Access: lab and
    # guest devices share private ranges, and nothing legitimate reaches the
    # dashboard by the LAN IP (owner decision 2026-10-13). Access-protected
    # public traffic always carries an assertion and arrives with the internet
    # client's address.
    try:
        address = ip_address(value.removeprefix("::ffff:"))
    except ValueError:
        return False
    return address.is_loopback


def _email_from_access_token(token: str) -> str:
    team = settings.cloudflare_access_team_domain.strip().removeprefix("https://").rstrip("/")
    aud = settings.agent_hub_cf_access_aud.strip()
    if not team or not aud:
        raise HTTPException(status_code=503, detail="Cloudflare Access is not configured")
    try:
        key = _jwk_client(team).get_signing_key_from_jwt(token)
        payload = jwt.decode(token, key.key, algorithms=["RS256"], audience=aud, issuer=f"https://{team}")
    except PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid Cloudflare Access token") from exc
    email = _payload_email(payload)
    if not email:
        raise HTTPException(status_code=401, detail="Cloudflare Access token has no email")
    return email.strip().lower()


def _payload_email(payload: dict[str, Any]) -> str | None:
    value = payload.get("email")
    if isinstance(value, str) and "@" in value:
        return value
    identity = payload.get("identity")
    if isinstance(identity, dict) and isinstance(identity.get("email"), str):
        return identity["email"]
    return None


@lru_cache(maxsize=4)
def _jwk_client(team: str) -> PyJWKClient:
    return PyJWKClient(f"https://{team}/cdn-cgi/access/certs", cache_keys=True)
