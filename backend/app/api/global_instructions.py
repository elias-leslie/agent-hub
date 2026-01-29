"""Global Instructions API endpoints.

Manage platform-wide instructions injected into all agents.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/global-instructions", tags=["global-instructions"])


class GlobalInstructionsResponse(BaseModel):
    """Response schema for global instructions."""

    id: int
    scope: str
    content: str
    enabled: bool
    updated_at: str
    applied_to_count: int


class GlobalInstructionsUpdateRequest(BaseModel):
    """Request schema for updating global instructions."""

    content: str | None = None
    enabled: bool | None = None


@router.get("", response_model=GlobalInstructionsResponse)
async def get_global_instructions(
    db: AsyncSession = Depends(get_db),
) -> GlobalInstructionsResponse:
    """Get global instructions (platform-wide scope)."""
    query = """
        SELECT gi.id, gi.scope, gi.content, gi.enabled, gi.updated_at,
               (SELECT COUNT(*) FROM agents WHERE is_active = true) as applied_to_count
        FROM global_instructions gi
        WHERE gi.scope = 'global'
    """
    result = await db.execute(text(query))
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Global instructions not found")

    return GlobalInstructionsResponse(
        id=row.id,
        scope=row.scope,
        content=row.content,
        enabled=row.enabled,
        updated_at=row.updated_at.isoformat() if row.updated_at else datetime.now(UTC).isoformat(),
        applied_to_count=row.applied_to_count or 0,
    )


@router.put("", response_model=GlobalInstructionsResponse)
async def update_global_instructions(
    request: GlobalInstructionsUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> GlobalInstructionsResponse:
    """Update global instructions."""
    updates = []
    params: dict[str, str | bool] = {"scope": "global"}

    if request.content is not None:
        updates.append("content = :content")
        params["content"] = request.content

    if request.enabled is not None:
        updates.append("enabled = :enabled")
        params["enabled"] = request.enabled

    if not updates:
        return await get_global_instructions(db)

    updates.append("updated_at = NOW()")

    query = f"""
        UPDATE global_instructions
        SET {", ".join(updates)}
        WHERE scope = :scope
        RETURNING id, scope, content, enabled, updated_at
    """

    result = await db.execute(text(query), params)
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Global instructions not found")

    await db.commit()

    count_result = await db.execute(text("SELECT COUNT(*) FROM agents WHERE is_active = true"))
    count = count_result.scalar() or 0

    logger.info(
        f"Updated global instructions: enabled={row.enabled}, content_length={len(row.content)}"
    )

    return GlobalInstructionsResponse(
        id=row.id,
        scope=row.scope,
        content=row.content,
        enabled=row.enabled,
        updated_at=row.updated_at.isoformat() if row.updated_at else datetime.now(UTC).isoformat(),
        applied_to_count=count,
    )
