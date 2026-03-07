"""Gemini adapter settings, OAuth credential resolution, and client factories."""

import json
import logging
from dataclasses import dataclass as _dataclass
from typing import Any

from google import genai
from google.genai.types import HttpOptions

logger = logging.getLogger(__name__)


@_dataclass
class GeminiSettings:
    """Encapsulated auth preferences for the Gemini adapter.

    Updated by the preferences API when the user changes settings.
    Checked at credential refresh time.
    """

    auth_preference: str = "api_key"  # "oauth" or "api_key"
    vertex_project: str = ""  # GCP project ID for CloudCode OAuth mode


_settings = GeminiSettings()


def set_gemini_auth_preference(preference: str) -> None:
    """Set the Gemini auth preference (called by the preferences API)."""
    if preference in ("oauth", "api_key"):
        _settings.auth_preference = preference


def get_gemini_auth_preference() -> str:
    """Get the current Gemini auth preference."""
    return _settings.auth_preference


def set_gemini_vertex_project(project: str) -> None:
    """Set the GCP project ID for CloudCode OAuth mode."""
    _settings.vertex_project = project


def get_gemini_vertex_project() -> str:
    """Get the GCP project ID for CloudCode OAuth mode."""
    return _settings.vertex_project


def resolve_oauth_data() -> dict[str, Any] | None:
    """Extract raw OAuth token data from DB credential manager.

    Returns a dict with access_token, refresh_token, project_id, expires_at
    or None if unavailable.
    """
    try:
        from app.services.credential_manager import get_credential_manager

        cm = get_credential_manager()
        if not cm.is_initialized:
            return None

        token_json = cm.get("gemini", "oauth_token")
        if not token_json:
            return None

        data = json.loads(token_json)
        access_token = data.get("access_token")
        if not access_token:
            return None

        refresh_token = cm.get("gemini", "refresh_token")
        project_id = data.get("project_id") or get_gemini_vertex_project()

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "project_id": project_id,
            "expires_at": data.get("expires_at"),
        }
    except Exception:
        logger.debug("Failed to resolve Gemini OAuth data", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Client factories
# ---------------------------------------------------------------------------


def make_sdk_client(api_key: str | None = None) -> genai.Client:
    """Create a GenAI SDK client with optional API key."""
    kwargs: dict[str, Any] = {"http_options": HttpOptions(timeout=300_000)}
    if api_key:
        kwargs["api_key"] = api_key
    return genai.Client(**kwargs)


def make_cloudcode_client(oauth_data: dict[str, Any]) -> Any:
    """Create a CloudCodeClient from resolved OAuth data."""
    from app.adapters.gemini_cloudcode import CloudCodeClient

    return CloudCodeClient(
        access_token=oauth_data["access_token"],
        refresh_token=oauth_data.get("refresh_token"),
        project_id=oauth_data["project_id"],
        expires_at=oauth_data.get("expires_at"),
    )


def pick_auth_mode(
    resolved_key: str | None,
    oauth_data: dict[str, Any] | None,
    preference: str,
) -> tuple[str, Any, Any]:
    """Select auth mode and create appropriate client(s).

    Returns (auth_mode, sdk_client_or_None, cloudcode_client_or_None).
    """
    oauth_usable = bool(
        oauth_data
        and oauth_data.get("access_token")
        and oauth_data.get("project_id")
    )
    if oauth_data and oauth_data.get("access_token") and not oauth_data.get("project_id"):
        logger.warning(
            "Gemini OAuth credentials found but project_id is missing — "
            "falling back to API key. Re-run the OAuth flow to fix."
        )

    if preference == "oauth" and oauth_usable:
        return "oauth", None, make_cloudcode_client(oauth_data)
    if resolved_key:
        return "api_key", make_sdk_client(resolved_key), None
    if oauth_usable:
        return "oauth", None, make_cloudcode_client(oauth_data)
    return "adc", make_sdk_client(), None
