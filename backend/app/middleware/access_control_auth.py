"""Authentication helpers for access control middleware."""

from time import monotonic
from typing import Any

from sqlalchemy import select

from app.db import async_session
from app.models import Client
from app.services.client_auth import verify_secret

# Client lookup cache: client_id -> (Client data dict, timestamp)
_client_cache: dict[str, tuple[dict[str, Any], float]] = {}
_CLIENT_CACHE_TTL = 600  # 10 minutes (internal service-to-service)


async def get_cached_client(client_id: str) -> dict[str, Any] | None:
    """Get client from cache or database.

    Returns dict with: id, secret_hash, status, display_name, suspension_reason, suspended_at
    """
    now = monotonic()

    if client_id in _client_cache:
        data, timestamp = _client_cache[client_id]
        if now - timestamp < _CLIENT_CACHE_TTL:
            return data
        del _client_cache[client_id]

    async with async_session() as db:
        result = await db.execute(select(Client).where(Client.id == client_id))
        client = result.scalar_one_or_none()
        if not client:
            return None

        data = {
            "id": str(client.id),
            "secret_hash": client.secret_hash,
            "status": client.status,
            "display_name": client.display_name,
            "suspension_reason": client.suspension_reason,
            "suspended_at": client.suspended_at,
            "allowed_projects": client.allowed_projects,
            "_client_obj": client,
        }
        _client_cache[client_id] = (data, now)
        return data


def invalidate_client_cache(client_id: str) -> None:
    """Invalidate cached client data (call after status changes)."""
    _client_cache.pop(client_id, None)


def verify_client_secret(client_secret: str, secret_hash: str, client_id: str) -> bool:
    """Verify client secret against hash (cached verification)."""
    return verify_secret(client_secret, secret_hash, client_id=client_id)


def detect_tool_type(source_client: str | None) -> str:
    """Detect tool type from X-Source-Client header.

    Returns:
        'cli' if source indicates CLI (e.g., 'st-cli')
        'sdk' if source indicates SDK (e.g., 'agent-hub-sdk')
        'api' otherwise (default)
    """
    if not source_client:
        return "api"
    source_lower = source_client.lower()
    if "cli" in source_lower:
        return "cli"
    if "sdk" in source_lower:
        return "sdk"
    return "api"
