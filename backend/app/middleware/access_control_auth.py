"""Client identification helpers for access control middleware."""

from time import monotonic
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import select

from app.db import async_session
from app.models import Client

# Client lookup cache: client_id -> (Client data dict, timestamp)
# Only primitive data is cached — never ORM objects (they become detached).
_client_cache: dict[str, tuple[dict[str, Any], float]] = {}
_CLIENT_CACHE_TTL = 600  # 10 minutes (internal service-to-service)
_CLIENT_CACHE_MAX_SIZE = 500


async def get_cached_client(client_id: str) -> dict[str, Any] | None:
    """Get client from cache or database.

    Returns dict with: id, status, display_name, rate_limit_rpm, rate_limit_tpm,
    allowed_projects, suspension_reason, suspended_at
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
            "status": client.status,
            "display_name": client.display_name,
            "rate_limit_rpm": client.rate_limit_rpm,
            "rate_limit_tpm": client.rate_limit_tpm,
            "allowed_projects": client.allowed_projects,
            "suspension_reason": client.suspension_reason,
            "suspended_at": client.suspended_at,
        }

        # Evict oldest entries if cache exceeds max size
        if len(_client_cache) >= _CLIENT_CACHE_MAX_SIZE:
            oldest_key = min(_client_cache, key=lambda k: _client_cache[k][1])
            del _client_cache[oldest_key]

        _client_cache[client_id] = (data, now)
        return data


def invalidate_client_cache(client_id: str) -> None:
    """Invalidate cached client data (call after status changes)."""
    _client_cache.pop(client_id, None)


async def require_service_client(request: Request) -> dict[str, Any]:
    """Verify the existing service secret and resolve its registered client binding.

    Ordinary X-Client-Id middleware is identification only. This stronger seam is
    used for scoped push and private receipt recovery, not human authentication.
    """
    from app.middleware.access_control_constants import CLIENT_ID_HEADER
    from app.middleware.access_control_paths import is_internal_request

    if not is_internal_request(request):
        raise HTTPException(status_code=401, detail="Verified internal service required.")
    client_id = request.headers.get(CLIENT_ID_HEADER)
    if not client_id:
        raise HTTPException(status_code=401, detail="Registered service client required.")
    client = await get_cached_client(client_id)
    if client is None or client.get("status") != "active":
        raise HTTPException(status_code=403, detail="Service client is not active.")
    return client


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
