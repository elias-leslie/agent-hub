"""Admin handlers and helper functions."""

from typing import Any

from .admin_redis import _deserialize_entry
from .admin_schemas import (
    RequestAuditLog,
    UnknownCallerStats,
)


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
