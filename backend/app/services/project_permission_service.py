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

# Persona-internal tools that modify Jenny's own config, not the project.
# Always allowed regardless of project tier (except "off").
_PERSONA_TOOLS: frozenset[str] = frozenset({
    "read_personality",
    "write_personality",
    "read_journal",
    "search_journal",
    "write_journal",
    "read_user_context",
    "write_user_context",
    "submit_onboarding",
    "mark_memory_relevant",
    "mark_memory_irrelevant",
    "manage_model_config",
    "log_agent_performance",
    "review_agent_performance",
})

_READ_TOOLS: frozenset[str] = frozenset({
    "read_file",
    "consult_agent",
    "read_personality",
    "read_journal",
    "search_journal",
    "read_user_context",
    "list_scheduled_jobs",
    "list_consultations",
})

_WRITE_TOOLS: frozenset[str] = _READ_TOOLS | frozenset({
    "write_file",
    "write_personality",
    "write_journal",
    "write_user_context",
    "mark_memory_relevant",
    "mark_memory_irrelevant",
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
# Tool permission checks (hot path)
# ---------------------------------------------------------------------------

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
        # 0. Persona-internal tools bypass project tier (they modify
        #    Jenny's own config, not the project codebase). Still
        #    blocked when tier is explicitly "off".
        if tool_name in _PERSONA_TOOLS:
            tier = await _get_cached_tier(project_id)
            if tier is None:
                if db is None:
                    from app.db import async_session
                    async with async_session() as fresh_db:
                        perm = await get_project_permission(fresh_db, project_id)
                else:
                    perm = await get_project_permission(db, project_id)
                tier = perm.permission_tier if perm else None
            if tier == "off":
                return False, "project permission tier is off"
            return True, "persona-internal tool (tier-exempt)"

        # 1. Try cache
        tier = await _get_cached_tier(project_id)

        # 2. Fall back to DB
        if tier is None:
            if db is None:
                from app.db import async_session
                async with async_session() as fresh_db:
                    perm = await get_project_permission(fresh_db, project_id)
            else:
                perm = await get_project_permission(db, project_id)

            if perm is None:
                # Unknown project — fail closed (deny access)
                logger.warning(
                    "No permission record for project %s — denying tool '%s'",
                    project_id, tool_name,
                )
                return False, f"no permission record for project '{project_id}'"
            else:
                tier = perm.permission_tier
                await _set_cache(project_id, tier, perm.auto_exec_enabled)

        # 3. Validate tier is recognized
        if tier not in TIER_TOOLS:
            logger.warning(
                "Unrecognized tier '%s' for project %s — denying tool '%s'",
                tier, project_id, tool_name,
            )
            return False, f"unrecognized permission tier '{tier}'"

        # 4. Check
        allowed_tools = get_tools_for_tier(tier)
        if tool_name in allowed_tools:
            return True, "allowed"

        return False, f"tool '{tool_name}' not permitted at tier '{tier}'"

    except Exception as e:
        # Fail-closed: any unexpected error denies access
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


async def check_execution_permission(
    db: AsyncSession, project_id: str
) -> ExecutionPermissionResult:
    """Check if automated execution is allowed for a project right now.

    Checks tier != "off", auto_exec_enabled, and time window.
    """
    perm = await get_project_permission(db, project_id)
    if perm is None:
        return ExecutionPermissionResult(
            allowed=False,
            permission_tier="unknown",
            auto_exec_enabled=False,
            in_time_window=False,
            reason="project_not_found",
        )

    tier = perm.permission_tier
    auto_exec = perm.auto_exec_enabled

    # Check tier
    if tier == "off":
        return ExecutionPermissionResult(
            allowed=False,
            permission_tier=tier,
            auto_exec_enabled=auto_exec,
            in_time_window=False,
            reason="permission_tier_off",
        )

    # Check auto_exec
    if not auto_exec:
        return ExecutionPermissionResult(
            allowed=False,
            permission_tier=tier,
            auto_exec_enabled=auto_exec,
            in_time_window=True,
            reason="auto_exec_disabled",
        )

    # Check time window
    current_hour = datetime.now().hour
    start = perm.execution_start_hour
    end = perm.execution_end_hour

    if start == end:
        # Zero-length window — never allowed (e.g., 0→0 or 10→10)
        in_window = False
    elif start < end:
        in_window = start <= current_hour < end
    else:
        # Wrap-around (e.g., 22 to 6)
        in_window = current_hour >= start or current_hour < end

    if not in_window:
        return ExecutionPermissionResult(
            allowed=False,
            permission_tier=tier,
            auto_exec_enabled=auto_exec,
            in_time_window=False,
            reason="outside_execution_hours",
        )

    return ExecutionPermissionResult(
        allowed=True,
        permission_tier=tier,
        auto_exec_enabled=auto_exec,
        in_time_window=True,
        reason="allowed",
    )
