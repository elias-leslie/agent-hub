"""Admin API endpoints for kill switch and usage control."""

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models import ClientControl

if TYPE_CHECKING:
    from redis.asyncio.client import Redis as AsyncRedis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# Request/Response schemas
class ClientControlResponse(BaseModel):
    """Response for client control status."""

    client_name: str
    enabled: bool
    disabled_at: datetime | None
    disabled_by: str | None
    reason: str | None
    created_at: datetime
    updated_at: datetime


class DisableRequest(BaseModel):
    """Request to disable a client."""

    reason: str | None = Field(default=None, max_length=500, description="Reason for disabling")
    disabled_by: str | None = Field(
        default=None, max_length=100, description="User/admin who disabled"
    )


class ClientListResponse(BaseModel):
    """Response for listing clients."""

    clients: list[ClientControlResponse]
    total: int


class BlockedRequestLog(BaseModel):
    """A log entry for a blocked request."""

    timestamp: datetime
    client_name: str | None
    source_path: str | None
    block_reason: str
    endpoint: str


class BlockedRequestsResponse(BaseModel):
    """Response for blocked requests log."""

    requests: list[BlockedRequestLog]
    total: int


class RequestAuditLog(BaseModel):
    """A log entry for any API request (for visibility)."""

    timestamp: datetime
    endpoint: str
    method: str
    client_name: str | None
    source_path: str | None
    user_agent: str | None
    referer: str | None
    client_ip: str | None
    status: str  # "allowed", "blocked", "unknown_client"


class RequestAuditResponse(BaseModel):
    """Response for request audit log."""

    requests: list[RequestAuditLog]
    total: int


class UnknownCallerStats(BaseModel):
    """Stats for an unknown caller (no X-Source-Client)."""

    fingerprint: str
    count: int
    first_seen: datetime | None
    last_seen: datetime | None
    endpoints: list[str]
    user_agents: list[str]


class UnknownCallersResponse(BaseModel):
    """Response for unknown callers list."""

    callers: list[UnknownCallerStats]
    total: int
    total_requests: int


# Redis keys for admin state (multi-worker safe)
REDIS_KEY_BLOCKED_REQUESTS = "ah:admin:blocked_requests"  # List (LPUSH/LRANGE)
REDIS_KEY_AUDIT_LOG = "ah:admin:audit_log"  # List (LPUSH/LRANGE)
REDIS_KEY_UNKNOWN_CALLERS = "ah:admin:unknown_callers"  # Hash (HSET/HGETALL)

# Max entries in logs
MAX_BLOCKED_LOG_SIZE = 1000
MAX_AUDIT_LOG_SIZE = 2000

# TTL for log entries (24 hours - logs auto-expire)
LOG_TTL_SECONDS = 86400

# Global Redis client (lazy initialized)
_redis_client: "AsyncRedis[str] | None" = None


async def get_admin_redis() -> "AsyncRedis[str] | None":
    """Get or create Redis client for admin state.

    Returns None if Redis is unavailable (caller should handle gracefully).
    """
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = aioredis.from_url(
                settings.agent_hub_redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            # Test connection
            await _redis_client.ping()
            logger.debug("Redis connected for admin state")
        except Exception as e:
            logger.warning(f"Redis unavailable for admin state: {e}")
            return None
    return _redis_client


async def _serialize_entry(entry: dict[str, Any]) -> str:
    """Serialize an entry for Redis storage."""
    # Convert datetime to ISO format for JSON serialization
    serializable: dict[str, Any] = {}
    for key, value in entry.items():
        if isinstance(value, datetime):
            serializable[key] = value.isoformat()
        elif isinstance(value, set):
            serializable[key] = list(value)
        else:
            serializable[key] = value
    return json.dumps(serializable)


def _deserialize_entry(data: str) -> dict[str, Any]:
    """Deserialize an entry from Redis storage."""
    entry: dict[str, Any] = json.loads(data)
    # Convert ISO strings back to datetime where applicable
    if "timestamp" in entry and isinstance(entry["timestamp"], str):
        entry["timestamp"] = datetime.fromisoformat(entry["timestamp"])
    if "first_seen" in entry and entry["first_seen"] and isinstance(entry["first_seen"], str):
        entry["first_seen"] = datetime.fromisoformat(entry["first_seen"])
    if "last_seen" in entry and entry["last_seen"] and isinstance(entry["last_seen"], str):
        entry["last_seen"] = datetime.fromisoformat(entry["last_seen"])
    return entry


async def log_blocked_request(
    client_name: str | None,
    source_path: str | None,
    block_reason: str,
    endpoint: str,
) -> None:
    """Log a blocked request for admin visibility.

    Uses Redis LIST for multi-worker safe storage.
    """
    redis = await get_admin_redis()
    if redis is None:
        logger.warning("Redis unavailable, skipping blocked request log")
        return

    entry = {
        "timestamp": datetime.now(UTC),
        "client_name": client_name,
        "source_path": source_path,
        "block_reason": block_reason,
        "endpoint": endpoint,
    }

    try:
        # LPUSH adds to head of list (newest first)
        await redis.lpush(REDIS_KEY_BLOCKED_REQUESTS, await _serialize_entry(entry))
        # LTRIM keeps only the most recent entries
        await redis.ltrim(REDIS_KEY_BLOCKED_REQUESTS, 0, MAX_BLOCKED_LOG_SIZE - 1)
        # Set TTL on first entry (refreshed with each LPUSH)
        await redis.expire(REDIS_KEY_BLOCKED_REQUESTS, LOG_TTL_SECONDS)
    except Exception as e:
        logger.warning(f"Failed to log blocked request to Redis: {e}")


async def log_request_audit(
    endpoint: str,
    method: str,
    client_name: str | None,
    source_path: str | None,
    user_agent: str | None,
    referer: str | None,
    client_ip: str | None,
    status: str,  # "allowed", "blocked", "unknown_client"
) -> None:
    """Log all requests to sensitive endpoints for audit visibility.

    This provides visibility into WHO is calling Agent Hub, even if they
    don't provide proper X-Source-Client headers.

    Uses Redis LIST for audit log and Redis HASH for unknown caller stats.
    """
    redis = await get_admin_redis()
    if redis is None:
        logger.warning("Redis unavailable, skipping audit log")
        return

    now = datetime.now(UTC)

    entry = {
        "timestamp": now,
        "endpoint": endpoint,
        "method": method,
        "client_name": client_name,
        "source_path": source_path,
        "user_agent": user_agent,
        "referer": referer,
        "client_ip": client_ip,
        "status": status,
    }

    try:
        # Log to audit list (LPUSH for newest-first ordering)
        await redis.lpush(REDIS_KEY_AUDIT_LOG, await _serialize_entry(entry))
        await redis.ltrim(REDIS_KEY_AUDIT_LOG, 0, MAX_AUDIT_LOG_SIZE - 1)
        await redis.expire(REDIS_KEY_AUDIT_LOG, LOG_TTL_SECONDS)

        # Track unknown callers (no X-Source-Client)
        if not client_name or client_name == "<unknown>":
            # Create a fingerprint from available info
            fingerprint = f"{user_agent or 'no-ua'}|{referer or 'no-ref'}|{client_ip or 'no-ip'}"

            # Get existing stats or create new
            existing = await redis.hget(REDIS_KEY_UNKNOWN_CALLERS, fingerprint)
            if existing:
                stats = _deserialize_entry(existing)
                # Convert lists back to sets for manipulation
                stats["endpoints"] = set(stats.get("endpoints", []))
                stats["user_agents"] = set(stats.get("user_agents", []))
            else:
                stats = {
                    "count": 0,
                    "first_seen": now,
                    "last_seen": None,
                    "endpoints": set(),
                    "user_agents": set(),
                }

            stats["count"] += 1
            stats["last_seen"] = now
            stats["endpoints"].add(endpoint)
            if user_agent:
                stats["user_agents"].add(user_agent)

            # Save back to Redis
            await redis.hset(
                REDIS_KEY_UNKNOWN_CALLERS,
                fingerprint,
                await _serialize_entry(stats),
            )
            await redis.expire(REDIS_KEY_UNKNOWN_CALLERS, LOG_TTL_SECONDS)
    except Exception as e:
        logger.warning(f"Failed to log audit to Redis: {e}")


# Client endpoints
@router.get("/clients", response_model=ClientListResponse)
async def list_clients(
    db: Annotated[AsyncSession, Depends(get_db)],
    include_enabled: bool = True,
    include_disabled: bool = True,
) -> ClientListResponse:
    """List all registered clients with their kill switch status."""
    query = select(ClientControl)

    if not include_enabled:
        query = query.where(ClientControl.enabled == False)  # noqa: E712
    if not include_disabled:
        query = query.where(ClientControl.enabled == True)  # noqa: E712

    query = query.order_by(ClientControl.client_name)
    result = await db.execute(query)
    clients = result.scalars().all()

    return ClientListResponse(
        clients=[
            ClientControlResponse(
                client_name=c.client_name,
                enabled=c.enabled,
                disabled_at=c.disabled_at,
                disabled_by=c.disabled_by,
                reason=c.reason,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
            for c in clients
        ],
        total=len(clients),
    )


@router.get("/clients/{client_name}", response_model=ClientControlResponse)
async def get_client(
    client_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClientControlResponse:
    """Get a specific client's status."""
    result = await db.execute(select(ClientControl).where(ClientControl.client_name == client_name))
    client = result.scalar_one_or_none()

    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    return ClientControlResponse(
        client_name=client.client_name,
        enabled=client.enabled,
        disabled_at=client.disabled_at,
        disabled_by=client.disabled_by,
        reason=client.reason,
        created_at=client.created_at,
        updated_at=client.updated_at,
    )


@router.post("/clients/{client_name}/disable", response_model=ClientControlResponse)
async def disable_client(
    client_name: str,
    request: DisableRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClientControlResponse:
    """Disable a client. Blocked requests will get 403 with retry_after=-1."""
    result = await db.execute(select(ClientControl).where(ClientControl.client_name == client_name))
    client = result.scalar_one_or_none()

    if not client:
        # Create new client control record
        client = ClientControl(
            client_name=client_name,
            enabled=False,
            disabled_at=datetime.now(UTC),
            disabled_by=request.disabled_by,
            reason=request.reason,
        )
        db.add(client)
    else:
        if not client.enabled:
            raise HTTPException(status_code=400, detail="Client already disabled")
        client.enabled = False
        client.disabled_at = datetime.now(UTC)
        client.disabled_by = request.disabled_by
        client.reason = request.reason

    await db.commit()
    await db.refresh(client)

    return ClientControlResponse(
        client_name=client.client_name,
        enabled=client.enabled,
        disabled_at=client.disabled_at,
        disabled_by=client.disabled_by,
        reason=client.reason,
        created_at=client.created_at,
        updated_at=client.updated_at,
    )


@router.delete("/clients/{client_name}/disable", response_model=ClientControlResponse)
async def enable_client(
    client_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClientControlResponse:
    """Re-enable a disabled client."""
    result = await db.execute(select(ClientControl).where(ClientControl.client_name == client_name))
    client = result.scalar_one_or_none()

    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    if client.enabled:
        raise HTTPException(status_code=400, detail="Client already enabled")

    client.enabled = True
    client.disabled_at = None
    client.disabled_by = None
    client.reason = None

    await db.commit()
    await db.refresh(client)

    return ClientControlResponse(
        client_name=client.client_name,
        enabled=client.enabled,
        disabled_at=client.disabled_at,
        disabled_by=client.disabled_by,
        reason=client.reason,
        created_at=client.created_at,
        updated_at=client.updated_at,
    )


# Blocked requests log endpoint
@router.get("/blocked-requests", response_model=BlockedRequestsResponse)
async def get_blocked_requests(
    limit: int = Query(default=100, ge=1, le=1000, description="Max entries to return"),
    client_name: str | None = Query(default=None, description="Filter by client"),
) -> BlockedRequestsResponse:
    """Get recent blocked request log entries."""
    redis = await get_admin_redis()
    if redis is None:
        return BlockedRequestsResponse(requests=[], total=0)

    try:
        # LRANGE gets entries from head (already in newest-first order from LPUSH)
        raw_entries = await redis.lrange(REDIS_KEY_BLOCKED_REQUESTS, 0, MAX_BLOCKED_LOG_SIZE - 1)
        requests = [_deserialize_entry(e) for e in raw_entries]

        # Filter by client if specified
        if client_name:
            requests = [r for r in requests if r.get("client_name") == client_name]

        # Already sorted by timestamp (newest first from LPUSH)
        # Apply limit
        requests = requests[:limit]

        return BlockedRequestsResponse(
            requests=[
                BlockedRequestLog(
                    timestamp=r["timestamp"],
                    client_name=r.get("client_name"),
                    source_path=r.get("source_path"),
                    block_reason=r["block_reason"],
                    endpoint=r["endpoint"],
                )
                for r in requests
            ],
            total=len(requests),
        )
    except Exception as e:
        logger.warning(f"Failed to read blocked requests from Redis: {e}")
        return BlockedRequestsResponse(requests=[], total=0)


# Request audit log endpoint (ALL requests, not just blocked)
@router.get("/request-audit", response_model=RequestAuditResponse)
async def get_request_audit(
    limit: int = Query(default=100, ge=1, le=1000, description="Max entries to return"),
    status: str | None = Query(
        default=None, description="Filter by status: allowed, blocked, unknown_client"
    ),
    endpoint_filter: str | None = Query(
        default=None, alias="endpoint", description="Filter by endpoint pattern"
    ),
) -> RequestAuditResponse:
    """Get recent request audit log for visibility into ALL API traffic.

    Use this to see what's connecting to Agent Hub, even before blocking.
    """
    redis = await get_admin_redis()
    if redis is None:
        return RequestAuditResponse(requests=[], total=0)

    try:
        # LRANGE gets entries from head (already in newest-first order from LPUSH)
        raw_entries = await redis.lrange(REDIS_KEY_AUDIT_LOG, 0, MAX_AUDIT_LOG_SIZE - 1)
        requests = [_deserialize_entry(e) for e in raw_entries]

        # Filter by status if specified
        if status:
            requests = [r for r in requests if r.get("status") == status]

        # Filter by endpoint pattern if specified
        if endpoint_filter:
            requests = [r for r in requests if endpoint_filter in r.get("endpoint", "")]

        # Already sorted by timestamp (newest first from LPUSH)
        # Apply limit
        requests = requests[:limit]

        return RequestAuditResponse(
            requests=[
                RequestAuditLog(
                    timestamp=r["timestamp"],
                    endpoint=r["endpoint"],
                    method=r["method"],
                    client_name=r.get("client_name"),
                    source_path=r.get("source_path"),
                    user_agent=r.get("user_agent"),
                    referer=r.get("referer"),
                    client_ip=r.get("client_ip"),
                    status=r["status"],
                )
                for r in requests
            ],
            total=len(requests),
        )
    except Exception as e:
        logger.warning(f"Failed to read audit log from Redis: {e}")
        return RequestAuditResponse(requests=[], total=0)


# Unknown callers endpoint
@router.get("/unknown-callers", response_model=UnknownCallersResponse)
async def get_unknown_callers(
    min_count: int = Query(default=1, ge=1, description="Minimum request count to include"),
) -> UnknownCallersResponse:
    """Get aggregated stats on callers that didn't provide X-Source-Client.

    This helps identify services/scripts that should be updated to include headers,
    or that should be blocked entirely.

    Callers are fingerprinted by: User-Agent + Referer + IP
    """
    redis = await get_admin_redis()
    if redis is None:
        return UnknownCallersResponse(callers=[], total=0, total_requests=0)

    try:
        # HGETALL returns dict of fingerprint -> stats JSON
        raw_stats = await redis.hgetall(REDIS_KEY_UNKNOWN_CALLERS)

        callers = []
        total_requests = 0

        for fingerprint, stats_json in raw_stats.items():
            stats = _deserialize_entry(stats_json)
            if stats["count"] >= min_count:
                callers.append(
                    UnknownCallerStats(
                        fingerprint=fingerprint,
                        count=stats["count"],
                        first_seen=stats["first_seen"],
                        last_seen=stats["last_seen"],
                        endpoints=list(stats.get("endpoints", [])),
                        user_agents=list(stats.get("user_agents", [])),
                    )
                )
                total_requests += stats["count"]

        # Sort by count descending (most active first)
        callers.sort(key=lambda x: x.count, reverse=True)

        return UnknownCallersResponse(
            callers=callers,
            total=len(callers),
            total_requests=total_requests,
        )
    except Exception as e:
        logger.warning(f"Failed to read unknown callers from Redis: {e}")
        return UnknownCallersResponse(callers=[], total=0, total_requests=0)


@router.delete("/unknown-callers")
async def clear_unknown_callers() -> dict[str, Any]:
    """Clear the unknown callers tracking data.

    Use after you've reviewed and addressed the unknown callers.
    """
    redis = await get_admin_redis()
    if redis is None:
        return {"cleared": 0, "message": "Redis unavailable"}

    try:
        # Get count before deleting
        count = await redis.hlen(REDIS_KEY_UNKNOWN_CALLERS)
        await redis.delete(REDIS_KEY_UNKNOWN_CALLERS)
        return {"cleared": count, "message": f"Cleared {count} unknown caller entries"}
    except Exception as e:
        logger.warning(f"Failed to clear unknown callers from Redis: {e}")
        return {"cleared": 0, "message": f"Error: {e}"}


@router.delete("/request-audit")
async def clear_request_audit() -> dict[str, Any]:
    """Clear the request audit log.

    Use after you've reviewed the audit log.
    """
    redis = await get_admin_redis()
    if redis is None:
        return {"cleared": 0, "message": "Redis unavailable"}

    try:
        # Get count before deleting
        count = await redis.llen(REDIS_KEY_AUDIT_LOG)
        await redis.delete(REDIS_KEY_AUDIT_LOG)
        return {"cleared": count, "message": f"Cleared {count} audit log entries"}
    except Exception as e:
        logger.warning(f"Failed to clear audit log from Redis: {e}")
        return {"cleared": 0, "message": f"Error: {e}"}
