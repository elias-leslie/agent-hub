"""Helper functions for Access Control API."""

from app.api.access_control_schemas import ClientResponse
from app.models import Client


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
        created_at=client.created_at,
        updated_at=client.updated_at,
        last_used_at=client.last_used_at,
        suspended_at=client.suspended_at,
        suspended_by=client.suspended_by,
        suspension_reason=client.suspension_reason,
    )
