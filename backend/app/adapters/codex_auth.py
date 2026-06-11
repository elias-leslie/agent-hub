"""Codex OAuth authentication utilities.

Handles OAuth PKCE flow and JWT token parsing for the ChatGPT backend API.
Credentials are managed externally; this module provides the token exchange
and refresh primitives.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.adapters._oauth_pkce import generate_pkce

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_AUTH_URL = "https://auth.openai.com/oauth/authorize"
CODEX_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_REDIRECT_URI = "http://localhost:1455/auth/callback"
CODEX_SCOPE = "openid profile email offline_access"
JWT_CLAIM_PATH = "https://api.openai.com/auth"


class CodexAuthError(RuntimeError):
    """Codex OAuth token refresh failed — the stored refresh token is dead.

    Distinguishes auth-chain death (operator must Re-auth in the dashboard)
    from transient provider errors so callers can alert on it specifically.
    """


# ---------------------------------------------------------------------------
# Credentials dataclass
# ---------------------------------------------------------------------------

@dataclass
class CodexCredentials:
    """Holds a set of Codex OAuth tokens and the derived account ID."""

    access_token: str
    refresh_token: str | None
    account_id: str  # Extracted from the JWT access token
    expires_at: float | None = None  # Unix timestamp (seconds)

    @property
    def is_expired(self) -> bool:
        """Return True if the access token has expired (or will within 60 s)."""
        if self.expires_at is None:
            return False
        return time.time() >= (self.expires_at - 60)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def _base64url_decode(data: str) -> bytes:
    """Decode base64url-encoded data with padding fixup."""
    # Add padding if missing
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data)


def _load_jwt_payload(access_token: str) -> dict[str, Any]:
    """Decode the unsigned JWT payload for local claim inspection."""
    parts = access_token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT: expected 3 dot-separated segments")

    payload_bytes = _base64url_decode(parts[1])
    payload = json.loads(payload_bytes)
    if not isinstance(payload, dict):
        raise ValueError("Invalid JWT payload: expected object")
    return payload


def extract_account_id(access_token: str) -> str:
    """Extract ``chatgpt_account_id`` from a JWT access token.

    The token is *not* signature-verified -- we only need the claim.
    """
    payload = _load_jwt_payload(access_token)

    auth_claim = payload.get(JWT_CLAIM_PATH)
    if not isinstance(auth_claim, dict):
        raise ValueError(f"JWT missing '{JWT_CLAIM_PATH}' claim")

    account_id = auth_claim.get("chatgpt_account_id")
    if not account_id or not isinstance(account_id, str):
        raise ValueError("JWT missing chatgpt_account_id in auth claim")

    return account_id


def extract_expires_at(access_token: str) -> float | None:
    """Extract the JWT ``exp`` claim, if present."""
    payload = _load_jwt_payload(access_token)
    exp = payload.get("exp")
    if isinstance(exp, (int, float)):
        return float(exp)
    return None


def parse_stored_oauth_token(raw_value: str | None) -> tuple[str | None, float | None]:
    """Parse a stored Codex OAuth token value.

    Supports both the legacy raw-JWT format and the structured JSON format used
    for refreshed tokens.
    """
    if not raw_value:
        return None, None

    try:
        data = json.loads(raw_value)
    except (json.JSONDecodeError, TypeError):
        return raw_value, extract_expires_at(raw_value)

    if not isinstance(data, dict):
        return raw_value, extract_expires_at(raw_value)

    access_token = data.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        return None, None

    expires_at = data.get("expires_at")
    if isinstance(expires_at, (int, float)):
        return access_token, float(expires_at)

    return access_token, extract_expires_at(access_token)


def serialize_stored_oauth_token(credentials: CodexCredentials) -> str:
    """Serialize Codex credentials for durable storage."""
    payload: dict[str, Any] = {"access_token": credentials.access_token}
    if credentials.expires_at is not None:
        payload["expires_at"] = credentials.expires_at
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# OAuth URL builder
# ---------------------------------------------------------------------------

def build_auth_url(state: str, code_challenge: str) -> str:
    """Build the OAuth authorization URL for browser redirect.

    Args:
        state: Anti-CSRF state parameter (random hex string).
        code_challenge: S256 PKCE code challenge.

    Returns:
        Fully-qualified authorization URL.
    """
    params = {
        "response_type": "code",
        "client_id": CODEX_CLIENT_ID,
        "redirect_uri": CODEX_REDIRECT_URI,
        "scope": CODEX_SCOPE,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "originator": "agent-hub",
    }
    return f"{CODEX_AUTH_URL}?{urlencode(params)}"


def create_auth_flow() -> dict[str, str]:
    """Create a full PKCE authorization flow.

    Returns a dict with keys: ``url``, ``state``, ``code_verifier``.
    The caller should store ``code_verifier`` and ``state`` for later
    exchange, and redirect the user to ``url``.
    """
    state = os.urandom(16).hex()
    code_verifier, code_challenge = generate_pkce()
    url = build_auth_url(state, code_challenge)
    return {
        "url": url,
        "state": state,
        "code_verifier": code_verifier,
    }


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------

async def exchange_code(code: str, code_verifier: str) -> CodexCredentials:
    """Exchange an authorization code for access + refresh tokens.

    Args:
        code: The authorization code received from the OAuth callback.
        code_verifier: The PKCE code verifier generated during ``create_auth_flow``.

    Returns:
        A :class:`CodexCredentials` instance.

    Raises:
        RuntimeError: If the token exchange fails.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            CODEX_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": CODEX_CLIENT_ID,
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": CODEX_REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if resp.status_code != 200:
        logger.error("Codex token exchange failed: %s %s", resp.status_code, resp.text)
        raise RuntimeError(f"Codex token exchange failed (HTTP {resp.status_code})")

    data = resp.json()
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")
    expires_in = data.get("expires_in")

    if not access_token:
        raise RuntimeError("Codex token response missing access_token")

    account_id = extract_account_id(access_token)
    expires_at = (time.time() + expires_in) if isinstance(expires_in, (int, float)) else None

    return CodexCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        account_id=account_id,
        expires_at=expires_at,
    )


async def refresh_access_token(refresh_token: str) -> CodexCredentials:
    """Refresh an expired access token.

    Args:
        refresh_token: The refresh token from a previous credential set.

    Returns:
        A new :class:`CodexCredentials` instance with fresh tokens.

    Raises:
        RuntimeError: If the refresh request fails.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            CODEX_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CODEX_CLIENT_ID,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if resp.status_code != 200:
        logger.error(
            "Codex token refresh failed: %s %s — fix: Agent Hub Settings → LLM Providers"
            " → Codex → Re-auth (wiki: codex-oauth-token-rotation)",
            resp.status_code,
            resp.text,
        )
        raise CodexAuthError(f"Codex token refresh failed (HTTP {resp.status_code})")

    data = resp.json()
    access_token = data.get("access_token")
    new_refresh_token = data.get("refresh_token")
    expires_in = data.get("expires_in")

    if not access_token:
        raise RuntimeError("Codex refresh response missing access_token")

    account_id = extract_account_id(access_token)
    expires_at = (time.time() + expires_in) if isinstance(expires_in, (int, float)) else None

    return CodexCredentials(
        access_token=access_token,
        refresh_token=new_refresh_token or refresh_token,
        account_id=account_id,
        expires_at=expires_at,
    )
