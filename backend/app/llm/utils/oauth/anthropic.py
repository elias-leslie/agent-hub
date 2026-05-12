"""Anthropic OAuth flow (Claude Pro/Max).

Port of pi-mono ``utils/oauth/anthropic.ts`` with two adaptations:

* HTTP via ``httpx`` (the agent-hub HTTP client).
* Redirect URI uses ``console.anthropic.com/oauth/code/callback`` (matching
  agent-hub's existing persisted tokens), not a local callback server. The
  user pastes the authorization code back via the ``on_prompt`` callback.

Shape mirrors pi-mono: a module-level :func:`login_anthropic` /
:func:`refresh_anthropic_token` plus :data:`anthropic_oauth_provider`
implementing :class:`OAuthProviderInterface`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .pkce import generate_pkce
from .types import (
    OAuthAuthInfo,
    OAuthCredentials,
    OAuthLoginCallbacks,
    OAuthPrompt,
)

logger = logging.getLogger(__name__)


# Constants — match agent-hub's existing client registration so persisted
# tokens (issued via console.anthropic.com) keep working.
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
SCOPES = "org:create_api_key user:profile user:inference"

# Pi-mono treats credentials as expired 5 minutes before the server's stated
# expiry to give downstream calls a safety margin.
_REFRESH_SAFETY_MARGIN_MS = 5 * 60 * 1000


def _parse_authorization_input(raw: str) -> tuple[str | None, str | None]:
    """Parse a user-pasted authorization payload.

    Accepts a full callback URL, a ``code#state`` pair, or a plain
    ``code`` string.
    """

    value = raw.strip()
    if not value:
        return None, None

    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        params = parse_qs(parsed.query)
        return (params.get("code", [None])[0], params.get("state", [None])[0])

    if "#" in value:
        code, state = value.split("#", 1)
        return code.strip() or None, state.strip() or None

    if "code=" in value:
        params = parse_qs(value)
        return (params.get("code", [None])[0], params.get("state", [None])[0])

    return value, None


async def _post_token(url: str, body: dict[str, str]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            url,
            json=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )

    if response.status_code != 200:
        raise RuntimeError(
            f"HTTP request failed. status={response.status_code}; url={url}; body={response.text}"
        )

    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"Token endpoint returned invalid JSON. url={url}; body={response.text}") from exc


async def _exchange_authorization_code(
    code: str,
    state: str,
    verifier: str,
    redirect_uri: str,
) -> OAuthCredentials:
    data = await _post_token(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": code,
            "state": state,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        },
    )

    access = data.get("access_token")
    refresh = data.get("refresh_token")
    expires_in = data.get("expires_in")
    if not isinstance(access, str) or not isinstance(refresh, str) or not isinstance(expires_in, int):
        raise RuntimeError(f"Token exchange response missing required fields: {data!r}")

    return OAuthCredentials(
        refresh=refresh,
        access=access,
        expires=int(time.time() * 1000) + expires_in * 1000 - _REFRESH_SAFETY_MARGIN_MS,
    )


async def login_anthropic(callbacks: OAuthLoginCallbacks) -> OAuthCredentials:
    """Run the Anthropic OAuth login flow (authorization code + PKCE)."""

    pkce = generate_pkce()
    auth_params = urlencode(
        {
            "code": "true",
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "code_challenge": pkce.challenge,
            "code_challenge_method": "S256",
            # Pi-mono parity: state == code_verifier.
            "state": pkce.verifier,
        }
    )

    callbacks.on_auth(
        OAuthAuthInfo(
            url=f"{AUTHORIZE_URL}?{auth_params}",
            instructions=(
                "Complete login in your browser, then paste the authorization "
                "code shown on the Anthropic page (or the full callback URL)."
            ),
        )
    )

    input_value = await callbacks.on_prompt(
        OAuthPrompt(
            message="Paste the authorization code or full redirect URL:",
            placeholder=REDIRECT_URI,
        )
    )
    code, state = _parse_authorization_input(input_value)
    if state and state != pkce.verifier:
        raise RuntimeError("OAuth state mismatch")
    if not code:
        raise RuntimeError("Missing authorization code")

    if callbacks.on_progress is not None:
        callbacks.on_progress("Exchanging authorization code for tokens...")

    return await _exchange_authorization_code(code, state or pkce.verifier, pkce.verifier, REDIRECT_URI)


async def refresh_anthropic_token(refresh_token: str) -> OAuthCredentials:
    """Refresh an Anthropic OAuth credential."""

    data = await _post_token(
        TOKEN_URL,
        {
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": refresh_token,
        },
    )

    access = data.get("access_token")
    refresh = data.get("refresh_token") or refresh_token
    expires_in = data.get("expires_in")
    if not isinstance(access, str) or not isinstance(refresh, str) or not isinstance(expires_in, int):
        raise RuntimeError(f"Anthropic token refresh response missing required fields: {data!r}")

    return OAuthCredentials(
        refresh=refresh,
        access=access,
        expires=int(time.time() * 1000) + expires_in * 1000 - _REFRESH_SAFETY_MARGIN_MS,
    )


class _AnthropicOAuthProvider:
    id = "anthropic"
    name = "Anthropic (Claude Pro/Max)"
    uses_callback_server = False

    async def login(self, callbacks: OAuthLoginCallbacks) -> OAuthCredentials:
        return await login_anthropic(callbacks)

    async def refresh_token(self, credentials: OAuthCredentials) -> OAuthCredentials:
        refreshed = await refresh_anthropic_token(credentials.refresh)
        # Preserve extras (e.g. account_id) across refresh.
        if credentials.extras:
            return replace(refreshed, extras={**credentials.extras})
        return refreshed

    def get_api_key(self, credentials: OAuthCredentials) -> str:
        return credentials.access

    def modify_models(self, models, credentials):
        return models


anthropic_oauth_provider: Any = _AnthropicOAuthProvider()


__all__ = [
    "CLIENT_ID",
    "REDIRECT_URI",
    "TOKEN_URL",
    "anthropic_oauth_provider",
    "login_anthropic",
    "refresh_anthropic_token",
]
