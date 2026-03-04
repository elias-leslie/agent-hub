"""OAuth token status helpers for each provider."""

from __future__ import annotations

import json
import time

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
    return ("authenticated" if oauth_token else "not_configured"), None


def check_google_token_status(provider: str) -> tuple[str, str | None]:
    """Return (oauth_status, email) for a Google-style (Gemini/Antigravity) JSON token."""
    cm = get_credential_manager()
    token_json = cm.get(provider, "oauth_token")
    if not token_json:
        return "not_configured", None

    try:
        data = json.loads(token_json)
    except (json.JSONDecodeError, TypeError):
        return "authenticated", None

    expires_at = data.get("expires_at")
    email: str | None = data.get("email")
    has_refresh = bool(cm.get(provider, "refresh_token"))

    if expires_at and time.time() >= expires_at and not has_refresh:
        return "expired", email

    return "authenticated", email
