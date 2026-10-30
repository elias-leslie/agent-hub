"""OpenCode Go subscription quota (5-hour, weekly, monthly), as reported by OpenCode.

The usage endpoint is not in OpenCode's public docs, so any HTTP or parse failure is reported as
"unavailable" instead of raising or inventing numbers. The key never appears in logs or results.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.llm.env_api_keys import get_env_api_key

logger = logging.getLogger(__name__)

PROVIDER = "opencode-go"
# Response keys in display order, with the labels the Costs page shows.
WINDOWS: tuple[tuple[str, str], ...] = (("rolling", "5 hours"), ("weekly", "Week"), ("monthly", "Month"))
# Length of each window as stored with the other providers' readings; a month is taken as 30 days.
WINDOW_MINUTES = {"rolling": 300, "weekly": 10080, "monthly": 43200}
USER_AGENT = "agent-hub/0.1.0"
_FAILURES = {401: "OpenCode rejected the API key.", 403: "No OpenCode Go subscription on this key."}

_cache: tuple[float, dict[str, Any]] | None = None


def session_id_file() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "agent-hub" / "opencode-session-id"


def install_session_id() -> str:
    """Stable per-install UUID sent as x-opencode-session; created on first use."""
    path = session_id_file()
    try:
        existing = path.read_text().strip()
        return str(uuid.UUID(existing))
    except (OSError, ValueError):
        pass
    new_id = str(uuid.uuid4())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_id + "\n")
    except OSError:
        logger.warning("could not persist the OpenCode session id")
    return new_id


def request_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "x-opencode-session": install_session_id(),
    }


def parse_usage(payload: Any) -> list[dict[str, Any]] | None:
    """The three windows, or None when the payload is not the shape we know."""
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return None
    windows: list[dict[str, Any]] = []
    for key, label in WINDOWS:
        raw = usage.get(key)
        if not isinstance(raw, dict):
            return None
        percent, status, resets = raw.get("percent"), raw.get("status"), raw.get("resetsAt")
        if isinstance(percent, bool) or not isinstance(percent, (int, float)) or not isinstance(status, str):
            return None
        resets_at: str | None = None
        if isinstance(resets, str):
            try:
                resets_at = datetime.fromisoformat(resets.replace("Z", "+00:00")).astimezone(UTC).isoformat()
            except ValueError:
                return None
        windows.append(
            {"key": key, "label": label, "status": status, "percent": max(0, min(100, round(percent))), "resets_at": resets_at}
        )
    return windows


def _result(state: str, *, windows: list[dict[str, Any]] | None = None, reason: str | None = None) -> dict[str, Any]:
    return {
        "provider": PROVIDER,
        "state": state,
        "reason": reason,
        "windows": windows or [],
        "fetched_at": datetime.now(UTC).isoformat(),
    }


async def _fetch(api_key: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=settings.opencode_go_usage_timeout_seconds) as client:
            response = await client.get(settings.opencode_go_usage_url, headers=request_headers(api_key))
    except httpx.HTTPError as exc:
        logger.warning("OpenCode Go usage request failed: %s", type(exc).__name__)
        return _result("unavailable", reason="Could not reach OpenCode.")
    if response.status_code != 200:
        logger.warning("OpenCode Go usage returned HTTP %s", response.status_code)
        return _result("unavailable", reason=_FAILURES.get(response.status_code, f"OpenCode returned HTTP {response.status_code}."))
    try:
        windows = parse_usage(response.json())
    except ValueError:
        windows = None
    if windows is None:
        logger.warning("OpenCode Go usage response had an unexpected shape")
        return _result("unavailable", reason="OpenCode's usage response changed shape.")
    return _result("ok", windows=windows)


async def get_usage() -> dict[str, Any]:
    """Quota windows, cached for a short time. Missing key reports "not_configured" and is never cached."""
    global _cache
    api_key = get_env_api_key(PROVIDER)
    if not api_key:
        return _result("not_configured", reason="No OpenCode Go API key is set for Agent Hub.")
    now = time.monotonic()
    if _cache and now - _cache[0] < settings.opencode_go_usage_cache_seconds:
        return _cache[1]
    result = await _fetch(api_key)
    _cache = (now, result)
    return result


def clear_cache() -> None:
    global _cache
    _cache = None
