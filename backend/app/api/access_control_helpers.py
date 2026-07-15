"""Helper functions for Access Control API."""

import json
from typing import Final

from fastapi import HTTPException, Request, status

from app.api.access_control_schemas import ClientResponse
from app.models import Client
from app.models.client import check_project_access

_STATE_MISSING: Final = object()


def parse_allowed_projects(allowed_projects_json: str | None) -> list[str] | None:
    """Parse allowed_projects JSON string to list."""
    if allowed_projects_json is None:
        return None
    try:
        projects = json.loads(allowed_projects_json)
        if isinstance(projects, list):
            return projects
        return None
    except (json.JSONDecodeError, TypeError):
        return None


def require_project_access(request: Request, project_id: str) -> None:
    """Require the authenticated request identity to authorize ``project_id``.

    Verified internal requests remain explicitly unrestricted. Identified clients
    with a null ``allowed_projects`` value are also explicitly unrestricted, while
    missing identity state or malformed project policy fails closed.
    """
    if getattr(request.state, "is_internal", False) is True:
        return

    client_id = getattr(request.state, "client_id", None)
    allowed_projects = getattr(request.state, "allowed_projects", _STATE_MISSING)
    if not isinstance(client_id, str) or not client_id or allowed_projects is _STATE_MISSING:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "project_identity_unavailable",
                "project_id": project_id,
                "message": "An identified client is required for project-scoped mutations.",
            },
        )

    if allowed_projects is not None and not isinstance(allowed_projects, str):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "project_access_policy_invalid",
                "client_id": client_id,
                "project_id": project_id,
                "message": "The identified client's project policy is invalid.",
            },
        )

    if not check_project_access(allowed_projects, project_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "project_access_denied",
                "client_id": client_id,
                "project_id": project_id,
                "message": "The identified client is not authorized for this project.",
            },
        )


def client_to_response(client: Client) -> ClientResponse:
    """Convert a Client model to ClientResponse schema."""
    return ClientResponse(
        client_id=client.id,
        display_name=client.display_name,
        client_type=client.client_type,
        status=client.status,
        rate_limit_rpm=client.rate_limit_rpm,
        rate_limit_tpm=client.rate_limit_tpm,
        allowed_projects=parse_allowed_projects(client.allowed_projects),
        created_at=client.created_at,
        updated_at=client.updated_at,
        last_used_at=client.last_used_at,
        suspended_at=client.suspended_at,
        suspended_by=client.suspended_by,
        suspension_reason=client.suspension_reason,
    )
