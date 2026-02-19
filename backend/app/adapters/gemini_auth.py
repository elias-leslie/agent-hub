"""Gemini OAuth authentication utilities.

Handles Google OAuth PKCE flow for Gemini CLI-style authentication.
Uses the same client credentials as the Gemini CLI (Cloud Code Assist)
so the redirect URI is fixed at http://localhost:8085/oauth2callback.
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
# Constants (from Gemini CLI OAuth app registration)
# ---------------------------------------------------------------------------

GEMINI_CLIENT_ID = "681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com"
GEMINI_CLIENT_SECRET = "GOCSPX-PLACEHOLDER_DO_NOT_USE"
GEMINI_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GEMINI_TOKEN_URL = "https://oauth2.googleapis.com/token"
GEMINI_REDIRECT_URI = "http://localhost:8085/oauth2callback"
GEMINI_SCOPES = (
    "https://www.googleapis.com/auth/cloud-platform "
    "https://www.googleapis.com/auth/userinfo.email "
    "https://www.googleapis.com/auth/userinfo.profile"
)
CODE_ASSIST_ENDPOINT = "https://cloudcode-pa.googleapis.com"
USERINFO_URL = "https://www.googleapis.com/oauth2/v1/userinfo"


# ---------------------------------------------------------------------------
# Credentials dataclass
# ---------------------------------------------------------------------------

@dataclass
class GeminiOAuthCredentials:
    """Holds a set of Gemini OAuth tokens."""

    access_token: str
    refresh_token: str | None
    expires_at: float | None = None
    project_id: str | None = None
    email: str | None = None

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

def create_gemini_auth_flow() -> dict[str, str]:
    """Create a full PKCE authorization flow for Gemini.

    Returns a dict with keys: ``url``, ``state``, ``code_verifier``.
    """
    state = os.urandom(16).hex()
    code_verifier, code_challenge = _generate_pkce()

    params = {
        "client_id": GEMINI_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": GEMINI_REDIRECT_URI,
        "scope": GEMINI_SCOPES,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    url = f"{GEMINI_AUTH_URL}?{urlencode(params)}"

    return {
        "url": url,
        "state": state,
        "code_verifier": code_verifier,
    }


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------

async def exchange_gemini_code(code: str, code_verifier: str) -> GeminiOAuthCredentials:
    """Exchange an authorization code for Gemini OAuth tokens.

    Args:
        code: The authorization code from the OAuth callback.
        code_verifier: The PKCE code verifier from ``create_gemini_auth_flow``.

    Returns:
        A :class:`GeminiOAuthCredentials` instance.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GEMINI_TOKEN_URL,
            data={
                "client_id": GEMINI_CLIENT_ID,
                "client_secret": GEMINI_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": GEMINI_REDIRECT_URI,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if resp.status_code != 200:
        logger.error("Gemini token exchange failed: %s %s", resp.status_code, resp.text)
        raise RuntimeError(f"Gemini token exchange failed (HTTP {resp.status_code})")

    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        raise RuntimeError("Gemini token response missing access_token")

    expires_in = data.get("expires_in")
    expires_at = (time.time() + expires_in) if isinstance(expires_in, (int, float)) else None

    return GeminiOAuthCredentials(
        access_token=access_token,
        refresh_token=data.get("refresh_token"),
        expires_at=expires_at,
    )


async def refresh_gemini_token(refresh_token: str) -> GeminiOAuthCredentials:
    """Refresh an expired Gemini access token."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GEMINI_TOKEN_URL,
            data={
                "client_id": GEMINI_CLIENT_ID,
                "client_secret": GEMINI_CLIENT_SECRET,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if resp.status_code != 200:
        logger.error("Gemini token refresh failed: %s %s", resp.status_code, resp.text)
        raise RuntimeError(f"Gemini token refresh failed (HTTP {resp.status_code})")

    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        raise RuntimeError("Gemini refresh response missing access_token")

    expires_in = data.get("expires_in")
    expires_at = (time.time() + expires_in) if isinstance(expires_in, (int, float)) else None

    return GeminiOAuthCredentials(
        access_token=access_token,
        refresh_token=data.get("refresh_token") or refresh_token,
        expires_at=expires_at,
    )


# ---------------------------------------------------------------------------
# Project discovery (Cloud Code Assist)
# ---------------------------------------------------------------------------

async def discover_project(access_token: str) -> str | None:
    """Discover or provision the GCP project for Cloud Code Assist.

    Returns the project ID, or None if discovery/provisioning fails.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Try to load existing Code Assist config
        resp = await client.post(
            f"{CODE_ASSIST_ENDPOINT}/v1internal:loadCodeAssist",
            headers=headers,
            json={},
        )

        if resp.status_code == 200:
            data = resp.json()
            project_id = data.get("gcpProjectId") or data.get("projectId")
            if project_id:
                return project_id

        # Try onboarding a new user
        resp = await client.post(
            f"{CODE_ASSIST_ENDPOINT}/v1internal:onboardUser",
            headers=headers,
            json={},
        )

        if resp.status_code != 200:
            logger.warning("Gemini onboardUser failed: %s", resp.status_code)
            return None

        data = resp.json()
        # May return an operation to poll
        operation_name = data.get("name")
        if operation_name and not data.get("done"):
            # Poll for completion (up to 30 seconds)
            for _ in range(15):
                import asyncio
                await asyncio.sleep(2)
                poll_resp = await client.get(
                    f"{CODE_ASSIST_ENDPOINT}/v1internal/{operation_name}",
                    headers=headers,
                )
                if poll_resp.status_code == 200:
                    poll_data = poll_resp.json()
                    if poll_data.get("done"):
                        result = poll_data.get("response", {})
                        return result.get("gcpProjectId") or result.get("projectId")

        return data.get("gcpProjectId") or data.get("projectId")


async def get_user_email(access_token: str) -> str | None:
    """Fetch the authenticated user's email from Google."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{USERINFO_URL}?alt=json",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code == 200:
        return resp.json().get("email")
    return None
