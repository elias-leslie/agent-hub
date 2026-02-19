"""Claude OAuth authentication utilities.

Handles the browser-based OAuth PKCE flow for Anthropic's Claude.
Uses the same client credentials as the Claude CLI so the redirect URI
is Anthropic's public code-display page (no local callback server needed).

Reference: pi-mono anthropic.ts
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (from Claude CLI / Anthropic OAuth app registration)
# ---------------------------------------------------------------------------

CLAUDE_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
CLAUDE_AUTH_URL = "https://claude.ai/oauth/authorize"
CLAUDE_TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
CLAUDE_REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
CLAUDE_SCOPES = "org:create_api_key user:profile user:inference"


# ---------------------------------------------------------------------------
# Credentials dataclass
# ---------------------------------------------------------------------------

@dataclass
class ClaudeOAuthCredentials:
    """Holds a set of Claude OAuth tokens."""

    access_token: str
    refresh_token: str | None
    expires_at: float | None = None

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() >= (self.expires_at - 60)


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------

def _generate_pkce() -> tuple[str, str]:
    """Generate a PKCE code verifier and S256 code challenge."""
    verifier_bytes = os.urandom(32)
    code_verifier = base64.urlsafe_b64encode(verifier_bytes).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


# ---------------------------------------------------------------------------
# OAuth URL builder
# ---------------------------------------------------------------------------

def create_claude_auth_flow() -> dict[str, str]:
    """Create a full PKCE authorization flow for Claude.

    Key differences from Codex/Gemini:
    - ``code=true`` param makes Anthropic display the code on their page
    - ``state`` equals ``code_verifier`` (per pi-mono pattern)
    - Redirect goes to Anthropic's public callback (no local server needed)

    Returns a dict with keys: ``url``, ``state``, ``code_verifier``.
    """
    code_verifier, code_challenge = _generate_pkce()
    # Per pi-mono: state == code_verifier
    state = code_verifier

    params = {
        "response_type": "code",
        "client_id": CLAUDE_CLIENT_ID,
        "redirect_uri": CLAUDE_REDIRECT_URI,
        "scope": CLAUDE_SCOPES,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "code": "true",
    }
    url = f"{CLAUDE_AUTH_URL}?{urlencode(params)}"

    return {
        "url": url,
        "state": state,
        "code_verifier": code_verifier,
    }


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------

def parse_claude_auth_input(raw: str) -> tuple[str, str]:
    """Parse user's pasted input from Anthropic's code display page.

    The page shows a code in ``code#state`` format.

    Returns:
        (code, state) tuple.

    Raises:
        ValueError: If the input cannot be parsed.
    """
    raw = raw.strip()
    if "#" in raw:
        code, state = raw.split("#", 1)
        return code.strip(), state.strip()
    raise ValueError("Expected code#state format from Anthropic's OAuth page")


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------

async def exchange_claude_code(
    code: str,
    code_verifier: str,
    state: str,
) -> ClaudeOAuthCredentials:
    """Exchange an authorization code for Claude OAuth tokens.

    Uses JSON body (not form-encoded, unlike Codex/Gemini).

    Args:
        code: The authorization code from the OAuth page.
        code_verifier: The PKCE code verifier from ``create_claude_auth_flow``.
        state: The state parameter (equals code_verifier for Claude).

    Returns:
        A :class:`ClaudeOAuthCredentials` instance.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            CLAUDE_TOKEN_URL,
            json={
                "grant_type": "authorization_code",
                "client_id": CLAUDE_CLIENT_ID,
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": CLAUDE_REDIRECT_URI,
            },
            headers={"Content-Type": "application/json"},
        )

    if resp.status_code != 200:
        logger.error("Claude token exchange failed: %s %s", resp.status_code, resp.text)
        raise RuntimeError(f"Claude token exchange failed (HTTP {resp.status_code})")

    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        raise RuntimeError("Claude token response missing access_token")

    expires_in = data.get("expires_in")
    expires_at = (time.time() + expires_in) if isinstance(expires_in, (int, float)) else None

    return ClaudeOAuthCredentials(
        access_token=access_token,
        refresh_token=data.get("refresh_token"),
        expires_at=expires_at,
    )


async def refresh_claude_token(refresh_token: str) -> ClaudeOAuthCredentials:
    """Refresh an expired Claude access token.

    Uses JSON body (not form-encoded).
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            CLAUDE_TOKEN_URL,
            json={
                "grant_type": "refresh_token",
                "client_id": CLAUDE_CLIENT_ID,
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/json"},
        )

    if resp.status_code != 200:
        logger.error("Claude token refresh failed: %s %s", resp.status_code, resp.text)
        raise RuntimeError(f"Claude token refresh failed (HTTP {resp.status_code})")

    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        raise RuntimeError("Claude refresh response missing access_token")

    expires_in = data.get("expires_in")
    expires_at = (time.time() + expires_in) if isinstance(expires_in, (int, float)) else None

    return ClaudeOAuthCredentials(
        access_token=access_token,
        refresh_token=data.get("refresh_token") or refresh_token,
        expires_at=expires_at,
    )
