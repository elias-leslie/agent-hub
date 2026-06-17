"""Project permissions API — centralized automation access control."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.projects import get_known_roots
from app.db import async_session, get_db
from app.models.memory_unified import Memory
from app.models.project_permission import VALID_PERMISSION_TIERS, normalize_permission_tier
from app.services.project_permission_service import (
    ExecutionPermissionResult,
    check_execution_permission,
    create_project_permission,
    delete_project_permission,
    get_project_permission,
    list_project_permissions,
    update_project_permission,
)

router = APIRouter(prefix="/projects", tags=["project-permissions"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ProjectPermissionResponse(BaseModel):
    """Response schema for a single project permission."""

    project_id: str
    permission_tier: str
    auto_exec_enabled: bool
    execution_start_hour: int
    execution_end_hour: int
    root_path: str | None
    daily_cost_budget_usd: float | None
    monthly_cost_budget_usd: float | None
    budget_alert_threshold: float
    updated_at: str
    created_at: str


class ProjectPermissionUpdate(BaseModel):
    """Request schema for updating a project permission."""

    permission_tier: str | None = Field(default=None, description="off, read, full")
    auto_exec_enabled: bool | None = None
    execution_start_hour: int | None = Field(default=None, ge=0, le=23)
    execution_end_hour: int | None = Field(default=None, ge=1, le=24)
    root_path: str | None = None
    daily_cost_budget_usd: float | None = Field(default=None, ge=0, description="Daily cost budget in USD, null=unlimited")
    monthly_cost_budget_usd: float | None = Field(default=None, ge=0, description="Monthly cost budget in USD, null=unlimited")
    budget_alert_threshold: float | None = Field(default=None, ge=0.0, le=1.0, description="Alert threshold 0.0-1.0")


class ProjectPermissionCreate(BaseModel):
    """Request schema for creating a project permission."""

    project_id: str = Field(min_length=1)
    permission_tier: str = Field(default="read", description="off, read, full")
    auto_exec_enabled: bool = False
    execution_start_hour: int = Field(default=0, ge=0, le=23)
    execution_end_hour: int = Field(default=24, ge=1, le=24)
    root_path: str | None = None
    daily_cost_budget_usd: float | None = Field(default=None, ge=0, description="Daily cost budget in USD, null=unlimited")
    monthly_cost_budget_usd: float | None = Field(default=None, ge=0, description="Monthly cost budget in USD, null=unlimited")
    budget_alert_threshold: float = Field(default=0.8, ge=0.0, le=1.0, description="Alert threshold 0.0-1.0")


class ExecutionPermissionResponse(BaseModel):
    """Lightweight yes/no response for SummitFlow pickup_guards."""

    allowed: bool
    permission_tier: str
    auto_exec_enabled: bool
    in_time_window: bool
    reason: str


class ProjectCatalogItem(BaseModel):
    """Selectable project identity for UI/context scoping."""

    project_id: str
    label: str
    root_path: str | None = None
    has_permission: bool
    has_root: bool
    has_memory: bool
    sources: list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_response(perm: Any) -> ProjectPermissionResponse:
    return ProjectPermissionResponse(
        project_id=perm.project_id,
        permission_tier=normalize_permission_tier(perm.permission_tier) or perm.permission_tier,
        auto_exec_enabled=perm.auto_exec_enabled,
        execution_start_hour=perm.execution_start_hour,
        execution_end_hour=perm.execution_end_hour,
        root_path=perm.root_path,
        daily_cost_budget_usd=perm.daily_cost_budget_usd,
        monthly_cost_budget_usd=perm.monthly_cost_budget_usd,
        budget_alert_threshold=perm.budget_alert_threshold,
        updated_at=perm.updated_at.isoformat() if perm.updated_at else "",
        created_at=perm.created_at.isoformat() if perm.created_at else "",
    )


def _project_label(project_id: str) -> str:
    return project_id.replace("-", " ").replace("_", " ")


def _memory_project_id(scope: str | None, scope_id: str | None, group_id: str | None) -> str | None:
    if scope_id:
        return scope_id
    if group_id and group_id.startswith("project-"):
        return group_id.removeprefix("project-")
    if scope and scope.startswith("project:"):
        return scope.split(":", 1)[1]
    return None


async def _list_memory_project_ids(db: AsyncSession) -> set[str]:
    """Return project IDs that exist only as memory/context scopes."""
    result = await db.execute(
        select(Memory.scope, Memory.scope_id, Memory.group_id)
        .where(
            or_(
                Memory.scope == "project",
                Memory.scope.like("project:%"),
                Memory.group_id.like("project-%"),
            )
        )
        .distinct()
    )
    project_ids: set[str] = set()
    for scope, scope_id, group_id in result.all():
        project_id = _memory_project_id(scope, scope_id, group_id)
        if project_id:
            project_ids.add(project_id)
    return project_ids


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/permissions", response_model=list[ProjectPermissionResponse])
async def list_permissions() -> list[ProjectPermissionResponse]:
    """List all project permissions."""
    async with async_session() as db:
        perms = await list_project_permissions(db)
        return [_to_response(p) for p in perms]


@router.get("/roots", response_model=dict[str, str])
async def list_project_roots() -> dict[str, str]:
    """List canonical project roots keyed by project ID."""
    return get_known_roots()


@router.get("/catalog", response_model=list[ProjectCatalogItem])
async def list_project_catalog(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ProjectCatalogItem]:
    """List all project IDs selectable for context scoping.

    This intentionally includes memory-only project scopes in addition to
    permission/root-backed projects so Runtime Context can manage contexts for
    projects that do not currently resolve to a local checkout.
    """
    permissions = await list_project_permissions(db)
    permission_by_id = {perm.project_id: perm for perm in permissions}
    roots = get_known_roots()
    memory_ids = await _list_memory_project_ids(db)
    project_ids = sorted(set(permission_by_id) | set(roots) | memory_ids)

    items: list[ProjectCatalogItem] = []
    for project_id in project_ids:
        perm = permission_by_id.get(project_id)
        root_path = getattr(perm, "root_path", None) or roots.get(project_id)
        sources: list[str] = []
        if perm is not None:
            sources.append("permission")
        if project_id in roots:
            sources.append("root")
        if project_id in memory_ids:
            sources.append("memory")
        items.append(
            ProjectCatalogItem(
                project_id=project_id,
                label=_project_label(project_id),
                root_path=root_path,
                has_permission=perm is not None,
                has_root=project_id in roots,
                has_memory=project_id in memory_ids,
                sources=sources,
            )
        )
    return items


@router.post("/permissions", response_model=ProjectPermissionResponse, status_code=201)
async def create_permission(
    payload: ProjectPermissionCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectPermissionResponse:
    """Create a new project permission row."""
    permission_tier = normalize_permission_tier(payload.permission_tier)
    if permission_tier is None:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tier '{payload.permission_tier}'. Must be one of: {', '.join(VALID_PERMISSION_TIERS)}",
        )

    if payload.execution_start_hour == payload.execution_end_hour:
        raise HTTPException(
            status_code=400,
            detail="start_hour and end_hour cannot be the same",
        )

    try:
        perm = await create_project_permission(
            db,
            payload.project_id,
            permission_tier=permission_tier,
            auto_exec_enabled=payload.auto_exec_enabled,
            execution_start_hour=payload.execution_start_hour,
            execution_end_hour=payload.execution_end_hour,
            root_path=payload.root_path,
            daily_cost_budget_usd=payload.daily_cost_budget_usd,
            monthly_cost_budget_usd=payload.monthly_cost_budget_usd,
            budget_alert_threshold=payload.budget_alert_threshold,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 409 if "already exists" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return _to_response(perm)


@router.get("/{project_id}/permissions", response_model=ProjectPermissionResponse)
async def get_permission(
    project_id: str,
) -> ProjectPermissionResponse:
    """Get permission for a single project."""
    async with async_session() as db:
        perm = await get_project_permission(db, project_id)
        if perm is None:
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
        return _to_response(perm)


@router.patch("/{project_id}/permissions", response_model=ProjectPermissionResponse)
async def update_permission(
    project_id: str,
    update: ProjectPermissionUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectPermissionResponse:
    """Update permission for a project (tier, auto_exec, hours, root_path)."""
    # Validate tier
    permission_tier = (
        normalize_permission_tier(update.permission_tier)
        if update.permission_tier is not None
        else None
    )
    if update.permission_tier is not None and permission_tier is None:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tier '{update.permission_tier}'. Must be one of: {', '.join(VALID_PERMISSION_TIERS)}",
        )

    # Validate hour range
    if (
        update.execution_start_hour is not None
        and update.execution_end_hour is not None
        and update.execution_start_hour == update.execution_end_hour
    ):
        raise HTTPException(
            status_code=400,
            detail="start_hour and end_hour cannot be the same",
        )

    # Build kwargs, only passing fields that were set
    kwargs: dict[str, Any] = {}
    if permission_tier is not None:
        kwargs["permission_tier"] = permission_tier
    if update.auto_exec_enabled is not None:
        kwargs["auto_exec_enabled"] = update.auto_exec_enabled
    if update.execution_start_hour is not None:
        kwargs["execution_start_hour"] = update.execution_start_hour
    if update.execution_end_hour is not None:
        kwargs["execution_end_hour"] = update.execution_end_hour
    if update.root_path is not None:
        kwargs["root_path"] = update.root_path
    if update.daily_cost_budget_usd is not None:
        kwargs["daily_cost_budget_usd"] = update.daily_cost_budget_usd
    if update.monthly_cost_budget_usd is not None:
        kwargs["monthly_cost_budget_usd"] = update.monthly_cost_budget_usd
    if update.budget_alert_threshold is not None:
        kwargs["budget_alert_threshold"] = update.budget_alert_threshold

    perm = await update_project_permission(db, project_id, **kwargs)
    if perm is None:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    # Invalidate budget cache when budget fields are updated
    budget_fields = {"daily_cost_budget_usd", "monthly_cost_budget_usd", "budget_alert_threshold"}
    if budget_fields & set(kwargs.keys()):
        from app.services.project_budget import invalidate_budget_cache

        await invalidate_budget_cache(project_id)

    return _to_response(perm)


@router.delete("/{project_id}/permissions", status_code=204)
async def delete_permission(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Delete the permission row for a project."""
    deleted = await delete_project_permission(db, project_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return Response(status_code=204)


@router.get(
    "/{project_id}/execution-permission",
    response_model=ExecutionPermissionResponse,
)
async def get_execution_permission(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ExecutionPermissionResponse:
    """Lightweight check: can automated execution proceed for this project?

    Used by SummitFlow's pickup_guards for fail-closed permission checks.
    """
    result: ExecutionPermissionResult = await check_execution_permission(db, project_id)
    return ExecutionPermissionResponse(
        allowed=result.allowed,
        permission_tier=result.permission_tier,
        auto_exec_enabled=result.auto_exec_enabled,
        in_time_window=result.in_time_window,
        reason=result.reason,
    )


@router.get("/budgets", response_model=list[dict])
async def get_all_project_budgets(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    """Get budget overview for all projects."""
    from app.services.project_budget import get_project_budget_usage

    perms = await list_project_permissions(db)
    budgets = []
    for perm in perms:
        usage = await get_project_budget_usage(perm.project_id)
        budgets.append(usage)
    return budgets


@router.get("/{project_id}/budget")
async def get_project_budget(project_id: str) -> dict:
    """Get current budget usage for a project."""
    from app.services.project_budget import get_project_budget_usage

    return await get_project_budget_usage(project_id)
