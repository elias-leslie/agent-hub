"""OAuth code exchange helpers: input parsers and per-provider exchange logic."""

from __future__ import annotations

import json
import logging
from urllib.parse import parse_qs, urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.claude_auth import exchange_claude_code, parse_claude_auth_input
from app.adapters.codex_auth import exchange_code as exchange_codex_code
from app.adapters.gemini_auth import (
    discover_project,
    exchange_antigravity_code,
    exchange_gemini_code,
    get_user_email,
)
from app.api.oauth_schemas import OAuthExchangeRequest
from app.api.oauth_store import upsert_credential

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input parsers
# ---------------------------------------------------------------------------


def parse_codex_input(raw: str) -> tuple[str, str | None]:
    """Parse Codex OAuth input: full URL, code#state, query string, or plain code."""
    raw = raw.strip()

    if raw.startswith("http"):
        parsed = urlparse(raw)
        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        if code:
            return code, params.get("state", [None])[0]

    if "#" in raw:
        code, state = raw.split("#", 1)
        return code.strip(), state.strip()

    if "code=" in raw:
        params = parse_qs(raw)
        code = params.get("code", [None])[0]
        if code:
            return code, params.get("state", [None])[0]

    return raw, None


def parse_gemini_input(raw: str) -> tuple[str, str | None]:
    """Parse Gemini/Antigravity OAuth input: full redirect URL or plain code."""
    raw = raw.strip()

    if raw.startswith("http"):
        parsed = urlparse(raw)
        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        if code:
            return code, params.get("state", [None])[0]

    return raw, None


# ---------------------------------------------------------------------------
# Per-provider exchange logic
# ---------------------------------------------------------------------------


async def exchange_claude(
    body: OAuthExchangeRequest, code_verifier: str, db: AsyncSession
) -> str | None:
    """Exchange Claude OAuth code and store credentials. Returns email or None."""
    code, _state = parse_claude_auth_input(body.code_input)
    creds = await exchange_claude_code(code, code_verifier, body.state)
    token_data = json.dumps({"access_token": creds.access_token, "expires_at": creds.expires_at})
    await upsert_credential(db, "claude", "oauth_token", token_data)
    if creds.refresh_token:
        await upsert_credential(db, "claude", "refresh_token", creds.refresh_token)
    return None


async def exchange_codex(
    body: OAuthExchangeRequest, code_verifier: str, db: AsyncSession
) -> str | None:
    """Exchange Codex OAuth code and store credentials. Returns email or None."""
    code, _state = parse_codex_input(body.code_input)
    creds = await exchange_codex_code(code, code_verifier)
    await upsert_credential(db, "codex", "oauth_token", creds.access_token)
    if creds.refresh_token:
        await upsert_credential(db, "codex", "refresh_token", creds.refresh_token)
    return None


async def exchange_google_provider(
    provider: str, body: OAuthExchangeRequest, code_verifier: str, db: AsyncSession
) -> str | None:
    """Exchange Gemini or Antigravity OAuth code and store credentials. Returns email."""
    code, _state = parse_gemini_input(body.code_input)
    if provider == "gemini":
        creds = await exchange_gemini_code(code, code_verifier)
    else:
        creds = await exchange_antigravity_code(code, code_verifier)

    project_id = await discover_project(creds.access_token)
    email = await get_user_email(creds.access_token)
    token_data = json.dumps(
        {
            "access_token": creds.access_token,
            "project_id": project_id,
            "email": email,
            "expires_at": creds.expires_at,
        }
    )
    await upsert_credential(db, provider, "oauth_token", token_data)
    if creds.refresh_token:
        await upsert_credential(db, provider, "refresh_token", creds.refresh_token)
    return email
