"""Project ownership inventory API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.ownership import OwnershipOwnerResponse, ProjectOwnershipResponse
from app.db import get_db
from app.services.ownership_inventory import query_project_ownership

router = APIRouter(prefix="/ownership", tags=["ownership"])


@router.get("/projects/{project_id}/live", response_model=ProjectOwnershipResponse)
async def get_live_project_ownership(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectOwnershipResponse:
    """Return normalized live ownership rows for a project."""
    owners = await query_project_ownership(db, project_id)
    return ProjectOwnershipResponse(
        project_id=project_id,
        generated_at=datetime.now(UTC),
        active_owners=[
            OwnershipOwnerResponse.model_validate(owner, from_attributes=True)
            for owner in owners
        ],
    )


__all__ = ["router"]
