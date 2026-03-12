"""Memory Episodes - Query and stats handler functions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from app.services.memory import MemoryService
from app.services.memory.service import MemoryCategory, MemoryListResult, MemoryStats

if TYPE_CHECKING:
    from .memory_schemas import HealthResponse

logger = logging.getLogger(__name__)


async def handle_list_episodes(
    memory: MemoryService,
    limit: int,
    cursor: str | None,
    category: MemoryCategory | None,
    all_groups: bool = False,
) -> MemoryListResult:
    """List memory episodes with cursor-based pagination."""
    try:
        return await memory.list_episodes(
            limit=limit,
            cursor=cursor,
            category=category,
            all_groups=all_groups,
        )
    except Exception as e:
        logger.exception("Failed to list episodes")
        raise HTTPException(status_code=500, detail=f"Failed to list episodes: {e}") from e


async def handle_get_memory_stats(
    memory: MemoryService,
    all_groups: bool = False,
) -> MemoryStats:
    """Get memory statistics."""
    try:
        return await memory.get_stats(all_groups=all_groups)
    except Exception as e:
        logger.exception("Failed to get memory stats")
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {e}") from e


async def handle_list_memory_scopes(memory: MemoryService) -> Any:
    """List all memory scopes with episode counts."""
    try:
        return await memory.get_scope_stats()
    except Exception as e:
        logger.exception("Failed to list memory scopes")
        raise HTTPException(status_code=500, detail=f"Failed to list scopes: {e}") from e


async def handle_get_episode_citations(full_uuid: str, limit: int) -> dict[str, Any]:
    """Get injection sessions where this episode was cited."""
    import json

    from sqlalchemy import select, text

    from app.db import _get_session_factory
    from app.models import MemoryInjectionMetric

    session_factory = _get_session_factory()
    try:
        async with session_factory() as session:
            stmt = (
                select(MemoryInjectionMetric)
                .where(text("CAST(memories_cited AS jsonb) @> CAST(:cited AS jsonb)"))
                .order_by(MemoryInjectionMetric.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt, {"cited": json.dumps([full_uuid])})
            records = result.scalars().all()

        return {
            "episode_uuid": full_uuid,
            "citations": [
                {
                    "session_id": r.session_id,
                    "project_id": r.project_id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "variant": r.variant or "BASELINE",
                }
                for r in records
            ],
            "total": len(records),
        }
    except Exception as e:
        logger.exception("Failed to get citations for %s", full_uuid)
        raise HTTPException(status_code=500, detail=f"Failed to get citations: {e}") from e


async def handle_memory_health(memory: MemoryService) -> HealthResponse:
    """Check memory system health."""
    from .memory_schemas import HealthResponse

    health = await memory.health_check()
    return HealthResponse(**health)
