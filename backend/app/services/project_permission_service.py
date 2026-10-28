"""Project permission service: CRUD for the registered-project row (root, budgets) and client access sync."""

from __future__ import annotations

import inspect
import json
import logging
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.projects import invalidate_project_cache
from app.core.project_roots import aresolve_project_root
from app.middleware.access_control_auth import invalidate_client_cache
from app.models.client import Client
from app.models.project_permission import ProjectPermission

logger = logging.getLogger(__name__)


_SUMMITFLOW_SYNC_CLIENTS: frozenset[str] = frozenset({"summitflow", "summitflow-backend"})


async def _flush_caches(changed_client_ids: list[str], *, project: bool = False) -> None:
    """Invalidate middleware caches after a project write."""
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
    return is_registry_synced_client(client.display_name)


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
        unregistered = _reconciled_registry is not None and project_id not in _reconciled_registry
        if enabled and not has_project and not unregistered:
            current_projects.append(project_id)
            client.allowed_projects = json.dumps(current_projects)
            changed_client_ids.append(str(client.id))
        elif not enabled and has_project:
            client.allowed_projects = json.dumps(
                [value for value in current_projects if value != project_id]
            )
            changed_client_ids.append(str(client.id))
    return changed_client_ids


async def reconcile_registered_project_access(
    db: AsyncSession, registered_project_ids: list[str] | None = None
) -> list[str]:
    """Repair SummitFlow-owned client access against permissions and the project registry.

    Every registered project is allowed, including projects that never got a
    permission row (they would otherwise be missing from the hand-grown list and
    their session ingestion would 403). With a known registry the list is exactly that set; without one (registry
    unavailable) the current list is only adjusted, never trimmed.
    """
    permission_result = await db.execute(
        select(ProjectPermission).order_by(ProjectPermission.project_id)
    )
    permissions = list(permission_result.scalars().all())
    managed_project_ids = [perm.project_id for perm in permissions]
    enabled_project_ids = list(managed_project_ids)
    for project_id in sorted(set(registered_project_ids or ()) - set(managed_project_ids)):
        managed_project_ids.append(project_id)
        enabled_project_ids.append(project_id)
    registry_known = bool(registered_project_ids)
    if registry_known:
        # SummitFlow only calls for registered projects: grant exactly those
        # and drop everything else the list picked up over time.
        registered = set(registered_project_ids or ())
        managed_project_ids = [project_id for project_id in managed_project_ids if project_id in registered]
        enabled_project_ids = [project_id for project_id in enabled_project_ids if project_id in registered]

    client_result = await db.execute(select(Client))
    clients = list(client_result.scalars().all())

    changed_client_ids: list[str] = []
    for client in clients:
        if not _should_sync_registered_project_access(client):
            continue
        current_projects = _parse_allowed_projects_json(client.allowed_projects)
        desired_projects = (
            list(enabled_project_ids)
            if registry_known
            else _merge_synced_allowed_projects(current_projects, managed_project_ids, enabled_project_ids)
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


_reconciled_registry: frozenset[str] | None = None


def is_registry_synced_client(display_name: str | None) -> bool:
    """Return whether a client's project access follows the SummitFlow registry."""
    return (display_name or "").strip().lower() in _SUMMITFLOW_SYNC_CLIENTS


async def reconcile_access_if_registry_changed() -> list[str]:
    """Re-run access reconciliation when the cached project registry changed.

    The registry is read through ``get_registered_project_roots`` (short TTL
    cache, last good copy on failure), so this is cheap per request and a
    newly registered SummitFlow project is allowed without a restart.
    """
    global _reconciled_registry
    from app.core.project_roots import ProjectRegistryUnavailable, get_registered_project_roots
    from app.db import async_session  # lazy import to avoid cycles

    try:
        registered = frozenset(await get_registered_project_roots())
    except ProjectRegistryUnavailable:
        return []
    if registered == _reconciled_registry:
        return []
    async with async_session() as db:
        changed = await reconcile_registered_project_access(db, sorted(registered))
    _reconciled_registry = registered
    return changed


async def create_project_permission(
    db: AsyncSession,
    project_id: str,
    *,
    root_path: str | None = None,
    daily_cost_budget_usd: float | None = None,
    monthly_cost_budget_usd: float | None = None,
    budget_alert_threshold: float = 0.8,
) -> ProjectPermission:
    """Create a new project row. Raises ValueError when project_id already exists."""
    existing = await get_project_permission(db, project_id)
    if existing is not None:
        raise ValueError(f"Project permission already exists for '{project_id}'")

    resolved_root_path = root_path
    if resolved_root_path is None:
        resolved_root = await aresolve_project_root(project_id)
        resolved_root_path = str(resolved_root) if resolved_root else None

    perm = ProjectPermission(
        project_id=project_id,
        root_path=resolved_root_path,
        daily_cost_budget_usd=daily_cost_budget_usd,
        monthly_cost_budget_usd=monthly_cost_budget_usd,
        budget_alert_threshold=budget_alert_threshold,
    )
    db.add(perm)
    changed_client_ids = await _sync_registered_project_access(
        db, project_id, enabled=True
    )
    await db.commit()
    await db.refresh(perm)
    await _flush_caches(changed_client_ids, project=True)
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
    await _flush_caches(changed_client_ids, project=True)
    return perm


def _apply_optional_fields(
    perm: ProjectPermission,
    *,
    root_path: Any,
    daily_cost_budget_usd: Any,
    monthly_cost_budget_usd: Any,
    budget_alert_threshold: float | None,
) -> None:
    """Mutate perm in-place for any non-sentinel kwargs."""
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
        root_path=root_path,
        daily_cost_budget_usd=daily_cost_budget_usd,
        monthly_cost_budget_usd=monthly_cost_budget_usd,
        budget_alert_threshold=budget_alert_threshold,
    )
    changed_client_ids = await _sync_registered_project_access(
        db, project_id, enabled=True
    )
    await db.commit()
    await db.refresh(perm)
    await _flush_caches(changed_client_ids)
    return perm
