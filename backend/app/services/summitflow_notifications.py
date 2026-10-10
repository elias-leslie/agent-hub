"""Create SummitFlow in-app notifications from Agent Hub.

Uses SummitFlow's existing ``POST /api/projects/{project_id}/notifications``
endpoint at the canonical local API URL from SummitFlow's ``.index.yaml``
(the same source ``backup_summary`` uses). Local requests need no credentials.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

import httpx

from app.services.backup_summary import _read_summitflow_api_url

logger = logging.getLogger(__name__)

NotificationSeverity = Literal["info", "warning", "error", "critical"]

AGENT_HUB_PROJECT_ID = "agent-hub"
_DEFAULT_TIMEOUT_S = 5.0
_background_tasks: set[asyncio.Task[bool]] = set()


async def create_summitflow_notification(
    *,
    title: str,
    message: str,
    severity: NotificationSeverity,
    metadata: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
    project_id: str = AGENT_HUB_PROJECT_ID,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> bool:
    """Create one ``system`` notification in SummitFlow. Returns True when accepted.

    ``dedupe_key`` scopes SummitFlow's system cooldown to this event stream so
    unrelated producers don't suppress each other; a deduplicated create returns
    204 and counts as accepted. Never raises: failures are logged so callers on hot paths stay unaffected.
    """
    api_base = await asyncio.to_thread(_read_summitflow_api_url)
    if not api_base:
        logger.warning("SummitFlow API URL unavailable; notification %r not sent", title)
        return False
    payload = {
        "type": "system",
        "title": title,
        "message": message,
        "severity": severity,
        "metadata": metadata or {},
    }
    if dedupe_key:
        payload["dedupe_key"] = dedupe_key
    url = f"{api_base.rstrip('/')}/projects/{project_id}/notifications"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
    except Exception as exc:
        logger.warning("Failed to create SummitFlow notification %r: %s", title, exc)
        return False
    return True


def spawn_summitflow_notification(**kwargs: Any) -> None:
    """Fire-and-forget ``create_summitflow_notification`` from a running loop."""
    task = asyncio.create_task(create_summitflow_notification(**kwargs))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
