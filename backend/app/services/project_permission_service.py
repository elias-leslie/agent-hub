"""Project permission service — CRUD, tier logic, and Redis cache.

Centralizes all automation permission decisions. Every tool execution and
auto-dispatch check flows through this service.
"""

from __future__ import annotations

import inspect
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants.projects import invalidate_project_cache
from app.core.project_roots import resolve_project_root
from app.middleware.access_control_auth import invalidate_client_cache
from app.models.client import Client
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
_REASON_MANAGE_TASKS_YOLO = "manage_tasks action requires yolo tier"
_REASON_DISPATCH_AGENT_YOLO = "dispatch_agent requires yolo tier"

# Reason strings for execution permission results
_EXEC_REASON_ALLOWED = "allowed"
_EXEC_REASON_PROJECT_NOT_FOUND = "project_not_found"
_EXEC_REASON_TIER_OFF = "permission_tier_off"
_EXEC_REASON_AUTO_EXEC_DISABLED = "auto_exec_disabled"
_EXEC_REASON_OUTSIDE_HOURS = "outside_execution_hours"

# Unknown tier sentinel for ExecutionPermissionResult
_TIER_UNKNOWN = "unknown"
_SUMMITFLOW_SYNC_CLIENTS: frozenset[str] = frozenset({"summitflow", "summitflow-backend"})


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
# project code. Safe coordination tools stay tier-exempt so the persona can
# operate during heartbeat/scheduler workflows regardless of the project's
# read/write tier. Tools that can launch or mutate project work are checked
# separately below.
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
    "search_persona_history",
})

_PERSONA_TOOLS: frozenset[str] = _PERSONA_INTERNAL | _PERSONA_OPERATIONAL

_SAFE_PERSONA_OPERATIONAL: frozenset[str] = frozenset({
    "manage_backups",
    "schedule_job",
    "cancel_scheduled_job",
    "send_push",
    "steer_consultation",
    "cancel_consultation",
    "query_sessions",
    "inspect_session",
    "search_persona_history",
})

_VISIBLE_PERSONA_TOOLS_BY_TIER: dict[str, frozenset[str]] = {
    "off": frozenset(),
    "read": _PERSONA_INTERNAL | _SAFE_PERSONA_OPERATIONAL,
    "write": _PERSONA_INTERNAL | _SAFE_PERSONA_OPERATIONAL,
    "yolo": _PERSONA_TOOLS,
}

_READ_SAFE_MANAGE_TASK_ACTIONS: frozenset[str] = frozenset({
    "overview",
    "get_context",
    "cleanup_status",
})

_READ_TOOLS: frozenset[str] = frozenset({
    "read_file",
    "consult_agent",
    "precision_code_search",
    "research_web",
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


def get_visible_tools_for_tier(tier: str) -> frozenset[str]:
    """Return tools that should be exposed up front for a project tier.

    This differs from runtime permission checks for persona tools: expose only
    the subset that is always callable for the tier. Tools like manage_tasks
    and dispatch_agent stay hidden until yolo because their runtime policy is
    action-sensitive or tier-sensitive and otherwise create visible-but-denied
    tool churn.
    """
    return get_tools_for_tier(tier) | _VISIBLE_PERSONA_TOOLS_BY_TIER.get(tier, frozenset())


async def get_visible_tools_for_project(
    project_id: str,
    db: AsyncSession | None = None,
) -> frozenset[str]:
    """Return the visible tool set for a project, failing closed on missing tier."""
    tier = await _resolve_project_tier(project_id, db)
    if tier is None:
        return frozenset()
    return get_visible_tools_for_tier(str(tier))


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


async def _flush_caches(
    project_id: str, changed_client_ids: list[str], *, project: bool = False
) -> None:
    """Invalidate Redis and middleware caches after a permission write."""
    await _invalidate_cache(project_id)
    for client_id in changed_client_ids:
        invalidate_client_cache(client_id)
    if project:
        invalidate_project_cache()


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
    permission = result.scalar_one_or_none()
    if inspect.isawaitable(permission):
        permission = await permission
    return cast(ProjectPermission | None, permission)


async def list_project_permissions(db: AsyncSession) -> list[ProjectPermission]:
    """List all project permission rows, ordered by project_id."""
    result = await db.execute(
        select(ProjectPermission).order_by(ProjectPermission.project_id)
    )
    return list(result.scalars().all())


def _merge_synced_allowed_projects(
    current_projects: list[str],
    managed_project_ids: list[str],
    enabled_project_ids: list[str],
) -> list[str]:
    """Return the normalized allowed-project list for SummitFlow-owned clients."""
    managed_project_set = set(managed_project_ids)
    enabled_project_set = set(enabled_project_ids)

    merged: list[str] = []
    for project_id in current_projects:
        if project_id in managed_project_set and project_id not in enabled_project_set:
            continue
        if project_id not in merged:
            merged.append(project_id)

    for project_id in enabled_project_ids:
        if project_id not in merged:
            merged.append(project_id)

    return merged


def _parse_allowed_projects_json(allowed_projects: str | None) -> list[str]:
    """Return a normalized allowed-project list from stored JSON."""
    if not allowed_projects:
        return []
    try:
        parsed = json.loads(allowed_projects)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    normalized: list[str] = []
    for value in parsed:
        if not isinstance(value, str):
            continue
        project_id = value.strip()
        if project_id and project_id not in normalized:
            normalized.append(project_id)
    return normalized


def _should_sync_registered_project_access(client: Client) -> bool:
    """Return whether this client should mirror SummitFlow-managed projects."""
    return client.display_name.strip().lower() in _SUMMITFLOW_SYNC_CLIENTS


async def _sync_registered_project_access(
    db: AsyncSession, project_id: str, *, enabled: bool
) -> list[str]:
    """Keep SummitFlow-owned Agent Hub clients aligned with registered projects."""
    result = await db.execute(select(Client))
    clients = list(result.scalars().all())
    changed_client_ids: list[str] = []
    for client in clients:
        if not _should_sync_registered_project_access(client):
            continue
        current_projects = _parse_allowed_projects_json(client.allowed_projects)
        has_project = project_id in current_projects
        if enabled and not has_project:
            current_projects.append(project_id)
            client.allowed_projects = json.dumps(current_projects)
            changed_client_ids.append(str(client.id))
        elif not enabled and has_project:
            client.allowed_projects = json.dumps(
                [value for value in current_projects if value != project_id]
            )
            changed_client_ids.append(str(client.id))
    return changed_client_ids


async def reconcile_registered_project_access(db: AsyncSession) -> list[str]:
    """Repair SummitFlow-owned client access against current project permissions."""
    permission_result = await db.execute(
        select(ProjectPermission).order_by(ProjectPermission.project_id)
    )
    permissions = list(permission_result.scalars().all())
    managed_project_ids = [perm.project_id for perm in permissions]
    enabled_project_ids = [
        perm.project_id for perm in permissions if str(perm.permission_tier).strip().lower() != "off"
    ]

    client_result = await db.execute(select(Client))
    clients = list(client_result.scalars().all())

    changed_client_ids: list[str] = []
    for client in clients:
        if not _should_sync_registered_project_access(client):
            continue
        current_projects = _parse_allowed_projects_json(client.allowed_projects)
        desired_projects = _merge_synced_allowed_projects(
            current_projects,
            managed_project_ids,
            enabled_project_ids,
        )
        if desired_projects == current_projects:
            continue
        client.allowed_projects = json.dumps(desired_projects)
        changed_client_ids.append(str(client.id))

    if changed_client_ids:
        await db.commit()
        for client_id in changed_client_ids:
            invalidate_client_cache(client_id)

    return changed_client_ids


def _validate_tier(tier: str) -> None:
    """Raise ValueError if tier is not a recognised permission tier."""
    if tier not in VALID_PERMISSION_TIERS:
        raise ValueError(f"Invalid tier: {tier}")


async def create_project_permission(
    db: AsyncSession,
    project_id: str,
    *,
    permission_tier: str = "read",
    auto_exec_enabled: bool = False,
    execution_start_hour: int = 0,
    execution_end_hour: int = 24,
    root_path: str | None = None,
    daily_cost_budget_usd: float | None = None,
    monthly_cost_budget_usd: float | None = None,
    budget_alert_threshold: float = 0.8,
) -> ProjectPermission:
    """Create a new project permission row.

    Raises ValueError when project_id already exists or the tier is invalid.
    """
    existing = await get_project_permission(db, project_id)
    if existing is not None:
        raise ValueError(f"Project permission already exists for '{project_id}'")

    _validate_tier(permission_tier)

    resolved_root_path = root_path
    if resolved_root_path is None:
        resolved_root = resolve_project_root(project_id)
        resolved_root_path = str(resolved_root) if resolved_root else None

    perm = ProjectPermission(
        project_id=project_id,
        permission_tier=permission_tier,
        auto_exec_enabled=auto_exec_enabled,
        execution_start_hour=execution_start_hour,
        execution_end_hour=execution_end_hour,
        root_path=resolved_root_path,
        daily_cost_budget_usd=daily_cost_budget_usd,
        monthly_cost_budget_usd=monthly_cost_budget_usd,
        budget_alert_threshold=budget_alert_threshold,
    )
    db.add(perm)
    changed_client_ids = await _sync_registered_project_access(
        db, project_id, enabled=permission_tier != "off"
    )
    await db.commit()
    await db.refresh(perm)
    await _flush_caches(project_id, changed_client_ids, project=True)
    return perm


async def delete_project_permission(
    db: AsyncSession, project_id: str
) -> ProjectPermission | None:
    """Delete a project permission row and remove mirrored SummitFlow access."""
    perm = await get_project_permission(db, project_id)
    if perm is None:
        return None

    changed_client_ids = await _sync_registered_project_access(
        db, project_id, enabled=False
    )
    await db.delete(perm)
    await db.commit()
    await _flush_caches(project_id, changed_client_ids, project=True)
    return perm


def _apply_optional_fields(
    perm: ProjectPermission,
    *,
    permission_tier: str | None,
    auto_exec_enabled: bool | None,
    execution_start_hour: int | None,
    execution_end_hour: int | None,
    root_path: Any,
    daily_cost_budget_usd: Any,
    monthly_cost_budget_usd: Any,
    budget_alert_threshold: float | None,
) -> None:
    """Mutate perm in-place for any non-sentinel kwargs; validate tier when provided."""
    if permission_tier is not None:
        _validate_tier(permission_tier)
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

    _apply_optional_fields(
        perm,
        permission_tier=permission_tier,
        auto_exec_enabled=auto_exec_enabled,
        execution_start_hour=execution_start_hour,
        execution_end_hour=execution_end_hour,
        root_path=root_path,
        daily_cost_budget_usd=daily_cost_budget_usd,
        monthly_cost_budget_usd=monthly_cost_budget_usd,
        budget_alert_threshold=budget_alert_threshold,
    )
    changed_client_ids = await _sync_registered_project_access(
        db, project_id, enabled=perm.permission_tier != "off"
    )
    await db.commit()
    await db.refresh(perm)
    await _flush_caches(project_id, changed_client_ids)
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


async def _resolve_project_tier(
    project_id: str, db: AsyncSession | None,
) -> str | None:
    """Return the cached or persisted permission tier for a project."""
    tier = await _get_cached_tier(project_id)
    if tier is not None:
        return tier
    perm = await _load_perm_from_db(project_id, db)
    return perm.permission_tier if perm else None


# ---------------------------------------------------------------------------
# Tool permission checks (hot path)
# ---------------------------------------------------------------------------

def _normalize_action(tool_input: dict[str, Any] | None) -> str | None:
    """Return a normalized tool action string, or None when absent."""
    if not tool_input:
        return None
    action = tool_input.get("action")
    if not isinstance(action, str):
        return None
    normalized = action.strip().lower()
    return normalized or None


async def _check_persona_tool_allowed(
    project_id: str,
    tool_name: str,
    tool_input: dict[str, Any] | None,
    db: AsyncSession | None,
) -> tuple[bool, str]:
    """Persona tools are blocked at off; mutating actions are further tier-gated."""
    tier = await _resolve_project_tier(project_id, db)
    if tier == "off":
        return False, _REASON_TIER_OFF
    if tool_name in _PERSONA_INTERNAL or tool_name in _SAFE_PERSONA_OPERATIONAL:
        return True, _REASON_PERSONA_EXEMPT
    if tool_name == "manage_tasks":
        action = _normalize_action(tool_input)
        if action in _READ_SAFE_MANAGE_TASK_ACTIONS:
            return True, _REASON_PERSONA_EXEMPT
        if tier == "yolo":
            return True, _REASON_ALLOWED
        return False, f"{_REASON_MANAGE_TASKS_YOLO}: '{action or 'unknown'}'"
    if tool_name == "dispatch_agent":
        if tier == "yolo":
            return True, _REASON_ALLOWED
        return False, _REASON_DISPATCH_AGENT_YOLO
    return True, _REASON_PERSONA_EXEMPT


async def check_tool_allowed(
    project_id: str,
    tool_name: str,
    *,
    tool_input: dict[str, Any] | None = None,
    db: AsyncSession | None = None,
) -> tuple[bool, str]:
    """Check whether a tool call is allowed for a project.

    Uses Redis cache for fast lookups. Falls back to DB on cache miss.
    All error paths fail-closed (deny access) for security.

    Returns:
        (allowed, reason) tuple.  Never raises.
    """
    try:
        if tool_name in _PERSONA_TOOLS:
            return await _check_persona_tool_allowed(project_id, tool_name, tool_input, db)

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
