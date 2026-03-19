"""Narration tags API — task progress timeline."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.storage.narration_tags import get_narration_tags_for_task

router = APIRouter(prefix="/narration", tags=["narration"])


class NarrationTagResponse(BaseModel):
    """Single narration tag in API response."""

    id: int
    task_id: str
    session_id: str
    tag_type: str
    content: str
    created_at: datetime


class NarrationTimelineResponse(BaseModel):
    """Narration tag timeline for a task."""

    task_id: str
    tags: list[NarrationTagResponse]
    total: int


@router.get("/tasks/{task_id}")
async def get_task_narration(
    task_id: str,
    tag_type: str | None = Query(default=None, description="Filter by tag type"),
    limit: int = Query(default=500, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
) -> NarrationTimelineResponse:
    """Get narration tag timeline for a task."""
    tags = await get_narration_tags_for_task(
        db, task_id, tag_type=tag_type, limit=limit
    )
    return NarrationTimelineResponse(
        task_id=task_id,
        tags=[
            NarrationTagResponse(
                id=tag.id,
                task_id=tag.task_id,
                session_id=tag.session_id,
                tag_type=tag.tag_type,
                content=tag.content,
                created_at=tag.created_at,
            )
            for tag in tags
        ],
        total=len(tags),
    )
