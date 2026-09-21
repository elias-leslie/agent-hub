"""OAuth token status helpers for supported providers."""

from __future__ import annotations

import time

from app.adapters.codex_auth import parse_stored_oauth_token
from app.config import settings
from app.services.codex_credentials import native_codex_credentials
from app.services.credential_manager import get_credential_manager


def check_codex_token_status() -> tuple[str, str | None]:
    """Return (oauth_status, email) for a Codex OAuth token."""
    if settings.codex_auth_authority == "native":
        native = native_codex_credentials()
        if native is None:
            return "not_configured", None
        return ("expired" if native.is_expired else "authenticated"), None

    cm = get_credential_manager()
    oauth_token = cm.get("codex", "oauth_token")
    access_token, expires_at = parse_stored_oauth_token(oauth_token)
    if not access_token:
        return "not_configured", None

    has_refresh = bool(cm.get("codex", "refresh_token"))
    if expires_at and time.time() >= expires_at and not has_refresh:
        return "expired", None

    return "authenticated", None
