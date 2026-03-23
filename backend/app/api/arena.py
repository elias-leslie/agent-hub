"""Arena API endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.agents import get_agent_service
from app.api.schemas.arena_schemas import ArenaOverviewResponse
from app.db import get_db
from app.services.api_key_auth import AuthenticatedKey, require_api_key
from app.services.arena_overview import get_arena_overview

router = APIRouter(prefix="/arena", tags=["arena"])


@router.get("/overview", response_model=ArenaOverviewResponse)
async def get_overview(
    db: Annotated[AsyncSession, Depends(get_db)],
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
    days: int = 30,
    project_id: str | None = None,
    primary_agent_slug: str = "persona",
) -> ArenaOverviewResponse:
    """Return one aggregated Arena payload for the command center."""
    service = get_agent_service()
    active_agents = await service.list_agents(db, active_only=True)
    payload = await get_arena_overview(
        db,
        active_agents=active_agents,
        days=days,
        project_id=project_id,
        primary_agent_slug=primary_agent_slug,
    )
    return ArenaOverviewResponse(**payload)
