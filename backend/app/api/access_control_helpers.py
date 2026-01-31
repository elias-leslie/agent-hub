"""Helper functions for Access Control API."""

import json

from app.api.access_control_schemas import ClientResponse
from app.models import Client


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


def client_to_response(client: Client) -> ClientResponse:
    """Convert a Client model to ClientResponse schema."""
    return ClientResponse(
        client_id=client.id,
        display_name=client.display_name,
        secret_prefix=client.secret_prefix,
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
