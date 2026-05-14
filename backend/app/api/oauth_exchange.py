"""OAuth code exchange helpers: input parsers and per-provider exchange logic."""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.codex_auth import exchange_code as exchange_codex_code
from app.adapters.codex_auth import serialize_stored_oauth_token
from app.api.oauth_schemas import OAuthExchangeRequest
from app.services.credential_upsert import upsert_credential

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


async def exchange_codex(
    body: OAuthExchangeRequest, code_verifier: str, db: AsyncSession
) -> str | None:
    """Exchange Codex OAuth code and store credentials. Returns email or None."""
    code, _state = parse_codex_input(body.code_input)
    creds = await exchange_codex_code(code, code_verifier)
    await upsert_credential(db, "codex", "oauth_token", serialize_stored_oauth_token(creds))
    if creds.refresh_token:
        await upsert_credential(db, "codex", "refresh_token", creds.refresh_token)
    return None
