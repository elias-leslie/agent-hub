"""Journal endpoint for the persona API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.memory.repository import get_memory_repository

from .schemas import JournalEntryResponse, JournalListResponse

router = APIRouter()


@router.get("/journal", response_model=JournalListResponse)
async def get_journal(
    days_back: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> JournalListResponse:
    """Get recent journal entries (read-only for UI)."""
    repo = get_memory_repository()
    since_dt = datetime.now(UTC) - timedelta(days=days_back)
    memories = await repo.list_by_scope_and_tier(
        scope="agent:persona",
        memory_type="journal",
        status="active",
        since=since_dt,
        order_by="created_at",
    )

    entries = [
        JournalEntryResponse(
            id=0,  # memories use UUID; id kept for schema compat
            entry_date=(m.valid_at or m.created_at).strftime("%Y-%m-%d"),
            content=m.content,
            entry_type=(m.metadata_ or {}).get("entry_type", "observation"),
            created_at=m.created_at.isoformat() if m.created_at else None,
        )
        for m in memories
    ]
    return JournalListResponse(entries=entries, total=len(entries))
