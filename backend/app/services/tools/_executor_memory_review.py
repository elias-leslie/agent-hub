"""Compatibility response for the retired memory review tool."""

from __future__ import annotations

import json


async def review_memory_system(
    action: str = "status",
    batch_limit: int = 10,
    max_batches: int = 1,
    cadence_days: int = 45,
    reviewer_agent_slug: str = "memory-curator",
    dry_run: bool = False,
    force_all: bool = False,
    include_archived: bool = False,
    only_missing_compact: bool = False,
    only_incomplete_audit: bool = False,
    schedule_type: str | None = None,
    schedule_value: str | None = None,
    timezone: str = "UTC",
    maintenance_request: dict | None = None,
) -> str:
    """Report retirement to callers holding an older tool catalog."""
    return json.dumps({
        "status": "unavailable",
        "error": "Memory Curator execution and scheduling are retired",
    }, separators=(",", ":"), sort_keys=True)
