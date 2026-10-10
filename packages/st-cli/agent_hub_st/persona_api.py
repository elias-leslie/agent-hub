"""Persona API client for the st persona CLI."""

from __future__ import annotations

from typing import Any

import httpx
from st_sdk.config import get_agent_hub_url
from st_sdk.credentials import load_credentials


def _get_url(path: str = "") -> str:
    """Build full persona API URL."""
    from ._api_paths import PERSONA_BASE_PATH

    return f"{get_agent_hub_url()}{PERSONA_BASE_PATH}{path}"


def _get_headers() -> dict[str, str]:
    """Build auth headers for Agent Hub access control."""
    client_id, request_source = load_credentials(default_source="st-persona")
    return {
        "X-Client-Id": client_id,
        "X-Request-Source": request_source,
    }


def get_persona() -> dict[str, Any]:
    """GET /api/persona — full persona config."""
    resp = httpx.get(_get_url(), headers=_get_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()


def update_persona(fields: dict[str, Any]) -> dict[str, Any]:
    """PUT /api/persona — partial update."""
    resp = httpx.put(_get_url(), json=fields, headers=_get_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_personality() -> dict[str, Any]:
    """GET /api/persona/personality — just the personality text."""
    resp = httpx.get(_get_url("/personality"), headers=_get_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()


def update_personality(personality: str, reason: str = "") -> dict[str, Any]:
    """PUT /api/persona/personality — update personality document."""
    resp = httpx.put(
        _get_url("/personality"),
        json={"personality": personality, "reason": reason},
        headers=_get_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_activity(time_range: str = "24h", page_size: int = 10) -> dict[str, Any]:
    """GET /api/persona/activity — paginated session history."""
    resp = httpx.get(
        _get_url("/activity"),
        params={"time_range": time_range, "page_size": page_size},
        headers=_get_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()

