"""Antigravity OAuth auth helpers for CloudCode Claude adapter."""

from __future__ import annotations

import logging
from typing import Any

from app.adapters.cloudcode_client import CloudCodeClient

logger = logging.getLogger(__name__)

# Antigravity endpoint fallback chain.
# The opencode reference tries: daily → autopush → prod.
_ANTIGRAVITY_ENDPOINTS = [
    "https://daily-cloudcode-pa.sandbox.googleapis.com",
    "https://autopush-cloudcode-pa.sandbox.googleapis.com",
    "https://cloudcode-pa.googleapis.com",
]

# HTTP headers for Antigravity content requests (v1.5.0+).
# Only User-Agent is required.  X-Goog-Api-Client, Client-Metadata, and
# X-Goog-User-Project were REMOVED in v1.5.0 and MUST NOT be sent.
# None values tell CloudCodeClient._headers() to strip the base defaults.
_ANTIGRAVITY_HEADERS: dict[str, str | None] = {
    "User-Agent": "antigravity/1.15.8 darwin/arm64",
    "X-Goog-Api-Client": None,      # strip base default (causes issues)
    "X-Goog-User-Project": None,    # must not be sent (causes 403)
}


def resolve_antigravity_oauth() -> dict[str, Any] | None:
    """Resolve Antigravity OAuth credentials from the credential manager.

    Tries Antigravity-specific credentials first, then falls back to
    Gemini CLI credentials (which may work if the user's Google account
    has Antigravity access).

    Returns a dict with ``access_token``, optionally ``refresh_token``,
    ``expires_at``, and ``project_id`` (from loadCodeAssist discovery).
    """
    try:
        import json

        from app.services.credential_manager import get_credential_manager

        cm = get_credential_manager()
        if not cm.is_initialized:
            return None

        # Try Antigravity-specific credentials first
        token_json = cm.get("antigravity", "oauth_token")
        if token_json:
            data = json.loads(token_json)
            if data.get("access_token"):
                refresh = cm.get("antigravity", "refresh_token")
                if refresh:
                    data["refresh_token"] = refresh
                return data

        # Fall back to Gemini CLI credentials
        from app.adapters.gemini import _resolve_oauth_data
        return _resolve_oauth_data()
    except Exception:
        logger.debug("Failed to resolve Antigravity OAuth data", exc_info=True)
        return None


def make_cc_client(endpoint_index: int = 0) -> CloudCodeClient | None:
    """Create a CloudCodeClient with Antigravity OAuth credentials.

    Uses ``user_agent="antigravity"``, minimal HTTP headers (v1.5.0+),
    and a discovered project ID from loadCodeAssist.
    """
    try:
        oauth_data = resolve_antigravity_oauth()
        if not oauth_data or not oauth_data.get("access_token"):
            return None
        project_id = oauth_data.get("project_id")
        if not project_id:
            logger.warning(
                "CloudCode Claude: no project_id discovered — "
                "re-authenticate via Antigravity OAuth"
            )
            return None
        return CloudCodeClient(
            access_token=oauth_data["access_token"],
            refresh_token=oauth_data.get("refresh_token"),
            project_id=project_id,
            expires_at=oauth_data.get("expires_at"),
            user_agent="antigravity",
            endpoint=_ANTIGRAVITY_ENDPOINTS[endpoint_index],
            extra_headers=_ANTIGRAVITY_HEADERS,
        )
    except Exception:
        logger.debug("Failed to create CloudCode client for Claude", exc_info=True)
        return None
