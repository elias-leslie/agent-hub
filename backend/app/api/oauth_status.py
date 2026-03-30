"""OAuth token status helpers for supported providers."""

from __future__ import annotations

import json
import time

from app.adapters.codex_auth import parse_stored_oauth_token
from app.services.credential_manager import get_credential_manager


def check_claude_token_status() -> tuple[str, str | None]:
    """Return (oauth_status, email) for a Claude OAuth token."""
    cm = get_credential_manager()
    token_json = cm.get("claude", "oauth_token")
    if not token_json:
        return "not_configured", None

    try:
        data = json.loads(token_json)
    except (json.JSONDecodeError, TypeError):
        return "authenticated", None

    expires_at = data.get("expires_at")
    email: str | None = data.get("email")
    has_refresh = bool(cm.get("claude", "refresh_token"))

    if expires_at and time.time() >= expires_at and not has_refresh:
        return "expired", email

    return "authenticated", email


def check_codex_token_status() -> tuple[str, str | None]:
    """Return (oauth_status, email) for a Codex OAuth token."""
    cm = get_credential_manager()
    oauth_token = cm.get("codex", "oauth_token")
    access_token, expires_at = parse_stored_oauth_token(oauth_token)
    if not access_token:
        return "not_configured", None

    has_refresh = bool(cm.get("codex", "refresh_token"))
    if expires_at and time.time() >= expires_at and not has_refresh:
        return "expired", None

    return "authenticated", None
