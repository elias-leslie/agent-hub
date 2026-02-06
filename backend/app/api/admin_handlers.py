"""Admin handlers and helper functions."""

from typing import Any

from app.models import ClientControl

from .admin_redis import _deserialize_entry
from .admin_schemas import (
    BlockedRequestLog,
    ClientControlResponse,
    RequestAuditLog,
    UnknownCallerStats,
)


def client_to_response(client: ClientControl) -> ClientControlResponse:
    """Convert ClientControl model to response schema."""
    return ClientControlResponse(
        client_name=client.client_name,
        enabled=client.enabled,
        disabled_at=client.disabled_at,
        disabled_by=client.disabled_by,
        reason=client.reason,
        created_at=client.created_at,
        updated_at=client.updated_at,
    )


def process_blocked_requests(
    raw_entries: list[str], client_name: str | None = None, limit: int = 100
) -> list[BlockedRequestLog]:
    """Process blocked request entries from Redis."""
    requests = [_deserialize_entry(e) for e in raw_entries]
    if client_name:
        requests = [r for r in requests if r.get("client_name") == client_name]
    return [
        BlockedRequestLog(
            timestamp=r["timestamp"],
            client_name=r.get("client_name"),
            source_path=r.get("source_path"),
            block_reason=r["block_reason"],
            endpoint=r["endpoint"],
        )
        for r in requests[:limit]
    ]


def process_audit_requests(
    raw_entries: list[str],
    status: str | None = None,
    endpoint_filter: str | None = None,
    limit: int = 100,
) -> list[RequestAuditLog]:
    """Process audit request entries from Redis."""
    requests = [_deserialize_entry(e) for e in raw_entries]
    if status:
        requests = [r for r in requests if r.get("status") == status]
    if endpoint_filter:
        requests = [r for r in requests if endpoint_filter in r.get("endpoint", "")]
    return [
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
        for r in requests[:limit]
    ]


def process_unknown_callers(
    raw_stats: dict[str, Any], min_count: int = 1
) -> tuple[list[UnknownCallerStats], int]:
    """Process unknown caller stats from Redis."""
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
    callers.sort(key=lambda x: x.count, reverse=True)
    return callers, total_requests
