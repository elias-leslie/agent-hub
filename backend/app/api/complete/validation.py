"""Validation logic for completion API requests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.api.complete.schemas import CompletionRequest


async def validate_agent_slug(
    request: CompletionRequest, db: AsyncSession | None
) -> None:
    """Validate that agent_slug is provided and accessible.

    Args:
        request: Completion request
        db: Database session

    Raises:
        HTTPException: If agent_slug is missing or invalid
    """
    if getattr(request, "adhoc", False) and request.agent_slug:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "adhoc_agent_conflict",
                "message": "Use either 'adhoc=true' or 'agent_slug', not both.",
            },
        )
    if getattr(request, "adhoc", False):
        return
    if not request.agent_slug:
        available_agents: list[str] = []
        if db:
            from app.services.agent_service import get_agent_service

            service = get_agent_service()
            agents = await service.list_agents(db, active_only=True, limit=50)
            available_agents = [f"{a.slug}: {a.description or a.name}" for a in agents]
        raise HTTPException(
            status_code=400,
            detail={
                "error": "agent_slug_required",
                "message": "'agent_slug' is required.",
                "available_agents": available_agents,
                "docs": "/api/agents",
            },
        )


def validate_project_access(
    request: CompletionRequest, allowed_projects: str | None
) -> None:
    """Validate client has access to the requested project.

    Args:
        request: Completion request
        allowed_projects: JSON string of allowed project_ids from client config,
            or None for unrestricted access (internal clients)

    Raises:
        HTTPException: If client is not authorized for project
    """
    if allowed_projects:
        from app.models.client import check_project_access

        if not check_project_access(allowed_projects, request.project_id):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "project_not_allowed",
                    "message": f"Client is not authorized for project '{request.project_id}'",
                    "project_id": request.project_id,
                },
            )
