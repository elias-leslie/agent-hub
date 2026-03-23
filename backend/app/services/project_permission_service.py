"""Project permission service — CRUD, tier logic, and Redis cache.

Centralizes all automation permission decisions. Every tool execution and
auto-dispatch check flows through this service.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.project_permission import VALID_PERMISSION_TIERS, ProjectPermission

logger = logging.getLogger(__name__)

# Redis cache configuration
_CACHE_PREFIX = "agent-hub:project-perm:"
_CACHE_TTL = 60  # seconds

# Singleton Redis client
_redis: aioredis.Redis | None = None

# Reason strings for tool permission results
_REASON_ALLOWED = "allowed"
_REASON_PERSONA_EXEMPT = "persona-internal tool (tier-exempt)"
_REASON_TIER_OFF = "project permission tier is off"

# Reason strings for execution permission results
_EXEC_REASON_ALLOWED = "allowed"
_EXEC_REASON_PROJECT_NOT_FOUND = "project_not_found"
_EXEC_REASON_TIER_OFF = "permission_tier_off"
_EXEC_REASON_AUTO_EXEC_DISABLED = "auto_exec_disabled"
_EXEC_REASON_OUTSIDE_HOURS = "outside_execution_hours"

# Unknown tier sentinel for ExecutionPermissionResult
_TIER_UNKNOWN = "unknown"


def _get_redis() -> aioredis.Redis:
    """Get or create async Redis client for permission cache."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.agent_hub_redis_url, encoding="utf-8", decode_responses=True
        )
    return _redis


# ---------------------------------------------------------------------------
# Tier → tool mapping (cumulative)
# ---------------------------------------------------------------------------

# Persona-internal tools that modify persona-owned config, not the project.
# Always allowed regardless of project tier (except "off").
_PERSONA_INTERNAL: frozenset[str] = frozenset({
    "read_personality",
    "write_personality",
    "read_user_context",
    "write_user_context",
    "read_heartbeat_instructions",
    "write_heartbeat_instructions",
    "submit_onboarding",
    "mark_memory_relevant",
    "mark_memory_irrelevant",
    "manage_memory_tags",
    "manage_model_config",
    "log_agent_performance",
    "review_agent_performance",
    "review_improvement_signals",
    "manage_feedback",
})

# Persona-operational tools — the persona's agency capabilities that don't modify
# project code. Task management, scheduling, notifications, and consultation
# steering. Tier-exempt so the persona can operate during heartbeat/scheduler
# workflows regardless of the project's read/write tier.
_PERSONA_OPERATIONAL: frozenset[str] = frozenset({
    "manage_tasks",
    "manage_backups",
    "schedule_job",
    "cancel_scheduled_job",
    "send_push",
    "steer_consultation",
    "cancel_consultation",
    "dispatch_agent",
    "query_sessions",
    "inspect_session",
})

_PERSONA_TOOLS: frozenset[str] = _PERSONA_INTERNAL | _PERSONA_OPERATIONAL

_READ_TOOLS: frozenset[str] = frozenset({
    "read_file",
    "consult_agent",
    "precision_code_search",
    "search_web",
    "fetch_web_page",
    "tool_search",
    "read_personality",
    "read_user_context",
    "list_scheduled_jobs",
    "list_consultations",
})

_WRITE_TOOLS: frozenset[str] = _READ_TOOLS | frozenset({
    "write_file",
    "write_personality",
    "write_user_context",
    "mark_memory_relevant",
    "mark_memory_irrelevant",
    "manage_memory_tags",
    "submit_onboarding",
})

_YOLO_TOOLS: frozenset[str] = _WRITE_TOOLS | frozenset({
    "bash",
    "send_push",
    "manage_tasks",
    "schedule_job",
    "cancel_scheduled_job",
    "steer_consultation",
    "cancel_consultation",
})

TIER_TOOLS: dict[str, frozenset[str]] = {
    "off": frozenset(),
    "read": _READ_TOOLS,
    "write": _WRITE_TOOLS,
    "yolo": _YOLO_TOOLS,
}


def get_tools_for_tier(tier: str) -> frozenset[str]:
    """Return the set of allowed tool names for a permission tier.

    Args:
        tier: One of "off", "read", "write", "yolo"

    Returns:
        Frozen set of allowed tool names. Empty set for "off".
    """
    return TIER_TOOLS.get(tier, frozenset())


# ---------------------------------------------------------------------------
# Redis cache helpers
# ---------------------------------------------------------------------------

def _cache_key(project_id: str) -> str:
    return f"{_CACHE_PREFIX}{project_id}"


async def _get_cached_tier(project_id: str) -> str | None:
    """Read cached permission tier from Redis. Returns None on miss."""
    try:
        r = _get_redis()
        data = await r.get(_cache_key(project_id))
        if data:
            return json.loads(data).get("tier")
    except Exception as e:
        logger.debug("Permission cache read error: %s", e)
    return None


async def _set_cache(project_id: str, tier: str, auto_exec: bool) -> None:
    """Write permission data to Redis cache."""
    try:
        r = _get_redis()
        await r.setex(
            _cache_key(project_id),
            _CACHE_TTL,
            json.dumps({"tier": tier, "auto_exec": auto_exec}),
        )
    except Exception as e:
        logger.debug("Permission cache write error: %s", e)


async def _invalidate_cache(project_id: str) -> None:
    """Remove permission from Redis cache (called on update)."""
    try:
        r = _get_redis()
        await r.delete(_cache_key(project_id))
    except Exception as e:
        logger.debug("Permission cache invalidate error: %s", e)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

async def get_project_permission(
    db: AsyncSession, project_id: str
) -> ProjectPermission | None:
    """Fetch a single project's permission row."""
    result = await db.execute(
        select(ProjectPermission).where(ProjectPermission.project_id == project_id)
    )
    return result.scalar_one_or_none()


async def list_project_permissions(db: AsyncSession) -> list[ProjectPermission]:
    """List all project permission rows, ordered by project_id."""
    result = await db.execute(
        select(ProjectPermission).order_by(ProjectPermission.project_id)
    )
    return list(result.scalars().all())


async def update_project_permission(
    db: AsyncSession,
    project_id: str,
    *,
    permission_tier: str | None = None,
    auto_exec_enabled: bool | None = None,
    execution_start_hour: int | None = None,
    execution_end_hour: int | None = None,
    root_path: str | None = ...,  # type: ignore[assignment]
    daily_cost_budget_usd: float | None = ...,  # type: ignore[assignment]
    monthly_cost_budget_usd: float | None = ...,  # type: ignore[assignment]
    budget_alert_threshold: float | None = None,
) -> ProjectPermission | None:
    """Update fields on an existing project permission row.

    Returns the updated row, or None if project_id not found.
    """
    perm = await get_project_permission(db, project_id)
    if perm is None:
        return None

    if permission_tier is not None:
        if permission_tier not in VALID_PERMISSION_TIERS:
            raise ValueError(f"Invalid tier: {permission_tier}")
        perm.permission_tier = permission_tier
    if auto_exec_enabled is not None:
        perm.auto_exec_enabled = auto_exec_enabled
    if execution_start_hour is not None:
        perm.execution_start_hour = execution_start_hour
    if execution_end_hour is not None:
        perm.execution_end_hour = execution_end_hour
    if root_path is not ...:
        perm.root_path = root_path
    if daily_cost_budget_usd is not ...:
        perm.daily_cost_budget_usd = daily_cost_budget_usd
    if monthly_cost_budget_usd is not ...:
        perm.monthly_cost_budget_usd = monthly_cost_budget_usd
    if budget_alert_threshold is not None:
        perm.budget_alert_threshold = budget_alert_threshold

    await db.commit()
    await db.refresh(perm)

    # Invalidate cache after update
    await _invalidate_cache(project_id)

    return perm


# ---------------------------------------------------------------------------
# Internal helpers for tool permission checks
# ---------------------------------------------------------------------------

async def _load_perm_from_db(
    project_id: str, db: AsyncSession | None
) -> ProjectPermission | None:
    """Load a permission row from DB, creating a session if none provided."""
    if db is not None:
        return await get_project_permission(db, project_id)
    from app.db import async_session  # lazy import to avoid cycles
    async with async_session() as fresh_db:
        return await get_project_permission(fresh_db, project_id)


# ---------------------------------------------------------------------------
# Tool permission checks (hot path)
# ---------------------------------------------------------------------------

async def _check_persona_tool_allowed(
    project_id: str, db: AsyncSession | None
) -> tuple[bool, str]:
    """Persona tools are tier-exempt; only blocked when tier is explicitly 'off'."""
    tier = await _get_cached_tier(project_id)
    if tier is None:
        perm = await _load_perm_from_db(project_id, db)
        tier = perm.permission_tier if perm else None
    if tier == "off":
        return False, _REASON_TIER_OFF
    return True, _REASON_PERSONA_EXEMPT


async def check_tool_allowed(
    project_id: str, tool_name: str, *, db: AsyncSession | None = None
) -> tuple[bool, str]:
    """Check whether a tool call is allowed for a project.

    Uses Redis cache for fast lookups. Falls back to DB on cache miss.
    All error paths fail-closed (deny access) for security.

    Returns:
        (allowed, reason) tuple.  Never raises.
    """
    try:
        if tool_name in _PERSONA_TOOLS:
            return await _check_persona_tool_allowed(project_id, db)

        # Regular tool: cache → DB → check
        tier = await _get_cached_tier(project_id)
        if tier is None:
            perm = await _load_perm_from_db(project_id, db)
            if perm is None:
                logger.warning(
                    "No permission record for project %s — denying tool '%s'",
                    project_id, tool_name,
                )
                return False, f"no permission record for project '{project_id}'"
            tier = perm.permission_tier
            await _set_cache(project_id, tier, perm.auto_exec_enabled)

        if tier not in TIER_TOOLS:
            logger.warning(
                "Unrecognized tier '%s' for project %s — denying tool '%s'",
                tier, project_id, tool_name,
            )
            return False, f"unrecognized permission tier '{tier}'"

        if tool_name in get_tools_for_tier(tier):
            return True, _REASON_ALLOWED
        return False, f"tool '{tool_name}' not permitted at tier '{tier}'"

    except Exception as e:
        logger.error(
            "Error checking tool permission for project %s, tool %s: %s",
            project_id, tool_name, e,
        )
        return False, f"permission check error: {e}"


# ---------------------------------------------------------------------------
# Execution permission (for SummitFlow API call)
# ---------------------------------------------------------------------------

@dataclass
class ExecutionPermissionResult:
    """Result of an execution permission check."""

    allowed: bool
    permission_tier: str
    auto_exec_enabled: bool
    in_time_window: bool
    reason: str


def _is_in_time_window(start: int, end: int, current_hour: int) -> bool:
    """Return True if current_hour falls within [start, end) with wrap-around support."""
    if start == end:
        return False  # zero-length window — never allowed
    if start < end:
        return start <= current_hour < end
    # Wrap-around (e.g., 22 to 6)
    return current_hour >= start or current_hour < end


async def check_execution_permission(
    db: AsyncSession, project_id: str
) -> ExecutionPermissionResult:
    """Check if automated execution is allowed for a project right now.

    Checks tier != "off", auto_exec_enabled, and time window.
    """
    # Helper alias for brevity
    R = ExecutionPermissionResult

    perm = await get_project_permission(db, project_id)
    if perm is None:
        return R(False, _TIER_UNKNOWN, False, False, _EXEC_REASON_PROJECT_NOT_FOUND)

    tier = perm.permission_tier
    auto_exec = perm.auto_exec_enabled

    if tier == "off":
        return R(False, tier, auto_exec, False, _EXEC_REASON_TIER_OFF)

    if not auto_exec:
        return R(False, tier, auto_exec, True, _EXEC_REASON_AUTO_EXEC_DISABLED)

    in_window = _is_in_time_window(
        perm.execution_start_hour, perm.execution_end_hour, datetime.now().hour
    )
    if not in_window:
        return R(False, tier, auto_exec, False, _EXEC_REASON_OUTSIDE_HOURS)

    return R(True, tier, auto_exec, True, _EXEC_REASON_ALLOWED)
