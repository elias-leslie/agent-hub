"""Server-derived application ownership for the shared push transport."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request

from app.config import settings
from app.middleware.access_control_auth import get_cached_client, require_service_client
from app.middleware.access_control_paths import INTERNAL_SERVICE_HEADER, is_internal_request


@dataclass(frozen=True)
class PushScope:
    application_id: str
    owner_id: str
    include_legacy: bool = False


def application_for_client(client: dict[str, Any]) -> str:
    """Use configured first-party identity or a single registered project.

    A caller's project_id/application_id never selects an application. Broad
    project access does not imply permission to send to all those applications.
    """
    if client["id"] in {"summitflow", settings.summitflow_client_id}:
        return "summitflow"
    try:
        projects = json.loads(client.get("allowed_projects") or "[]")
    except (TypeError, json.JSONDecodeError):
        projects = []
    if isinstance(projects, list) and len(projects) == 1 and isinstance(projects[0], str) and projects[0]:
        return projects[0]
    raise HTTPException(status_code=403, detail="Client has no unambiguous push application binding.")


async def resolve_push_scope(request: Request, application_id: str | None) -> PushScope:
    verified = is_internal_request(request)
    if verified:
        client = await require_service_client(request)
    else:
        if application_id is not None or request.headers.get(INTERNAL_SERVICE_HEADER) is not None:
            raise HTTPException(status_code=401, detail="Verified internal service required.")
        # Explicit compatibility path for the existing SummitFlow proxy. This
        # preserves its identified localhost trust; it cannot reach other apps.
        client_id = getattr(request.state, "client_id", None)
        client = await get_cached_client(client_id) if client_id else None
        if client is None or client.get("status") != "active":
            raise HTTPException(status_code=401, detail="Verified internal service required.")
    bound_application = application_for_client(client)
    if not verified and bound_application != "summitflow":
        raise HTTPException(status_code=401, detail="Verified internal service required.")
    if application_id is not None and application_id != bound_application:
        raise HTTPException(status_code=403, detail="Application differs from the service binding.")
    return PushScope(
        application_id=bound_application,
        owner_id=str(client["id"]),
        include_legacy=not verified,
    )
