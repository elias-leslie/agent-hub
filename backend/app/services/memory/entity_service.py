"""Entity browser service using PostgreSQL memory_entities table."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import and_, func, select

from app.db import async_session
from app.models.memory_unified import Memory, MemoryEntity, MemoryEntityMention

logger = logging.getLogger(__name__)


async def list_entities(
    driver: Any,
    group_id: str,
    search: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    """List entities from memory_entities table.

    The ``driver`` parameter is accepted but ignored for backward compatibility.
    All data is fetched from PostgreSQL.
    """
    try:
        async with async_session() as session:
            # Build base query
            conditions = [MemoryEntity.scope == group_id]
            if search:
                conditions.append(MemoryEntity.name.ilike(f"%{search}%"))

            # Get total count
            count_stmt = select(func.count(MemoryEntity.id)).where(and_(*conditions))
            total_result = await session.execute(count_stmt)
            total = total_result.scalar() or 0

            # Get entities with pagination
            stmt = (
                select(MemoryEntity)
                .where(and_(*conditions))
                .order_by(MemoryEntity.mention_count.desc())
                .offset(offset)
                .limit(limit)
            )
            result = await session.execute(stmt)
            entities_rows = list(result.scalars().all())

            entities = [
                {
                    "name": e.name,
                    "uuid": str(e.id),
                    "group_id": e.scope,
                    "created_at": e.created_at,
                    "summary": e.summary,
                    "episode_count": e.mention_count,
                    "edge_count": 0,  # No longer tracked via graph edges
                }
                for e in entities_rows
            ]
            return {"entities": entities, "total": total}
    except Exception:
        logger.exception("Failed to list entities for group_id=%s", group_id)
        raise


async def get_entity_episodes(
    driver: Any,
    entity_name: str,
    group_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Get memories mentioning a specific entity.

    The ``driver`` parameter is accepted but ignored for backward compatibility.
    Uses the memory_entity_mentions join table to find related memories.
    """
    try:
        async with async_session() as session:
            # Find entity
            entity_stmt = select(MemoryEntity.id).where(
                MemoryEntity.name == entity_name,
                MemoryEntity.scope == group_id,
            )
            entity_result = await session.execute(entity_stmt)
            entity_id = entity_result.scalar()

            if not entity_id:
                return []

            # Find memories via mentions
            stmt = (
                select(Memory)
                .join(MemoryEntityMention, MemoryEntityMention.memory_id == Memory.id)
                .where(MemoryEntityMention.entity_id == entity_id)
                .order_by(Memory.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            memories = list(result.scalars().all())

            from .repository import TIER_REVERSE

            return [
                {
                    "uuid": str(m.id),
                    "content": m.content[:300] if m.content else "",
                    "injection_tier": TIER_REVERSE.get(m.tier, "reference"),
                    "created_at": m.created_at,
                }
                for m in memories
            ]
    except Exception:
        logger.exception("Failed to get episodes for entity=%s", entity_name)
        raise


async def get_entity_health(
    driver: Any,
    group_id: str,
) -> dict[str, Any]:
    """Get entity health metrics from PostgreSQL.

    The ``driver`` parameter is accepted but ignored for backward compatibility.
    """
    try:
        async with async_session() as session:
            # Total entities
            total_stmt = select(func.count(MemoryEntity.id)).where(
                MemoryEntity.scope == group_id
            )
            total_result = await session.execute(total_stmt)
            total_entities = total_result.scalar() or 0

            # Orphan entities (no mentions)
            orphan_stmt = select(func.count(MemoryEntity.id)).where(
                MemoryEntity.scope == group_id,
                MemoryEntity.mention_count == 0,
            )
            orphan_result = await session.execute(orphan_stmt)
            orphan_count = orphan_result.scalar() or 0

            # Duplicate entity names
            dup_stmt = (
                select(MemoryEntity.name, func.count(MemoryEntity.id).label("cnt"))
                .where(MemoryEntity.scope == group_id)
                .group_by(MemoryEntity.name)
                .having(func.count(MemoryEntity.id) > 1)
            )
            dup_result = await session.execute(dup_stmt)
            dup_rows = dup_result.all()
            duplicate_count = len(dup_rows)
            duplicate_names = [r[0] for r in dup_rows[:20]]

            # Total mentions (proxy for edges)
            mention_stmt = (
                select(func.count(MemoryEntityMention.id))
                .join(MemoryEntity, MemoryEntityMention.entity_id == MemoryEntity.id)
                .where(MemoryEntity.scope == group_id)
            )
            mention_result = await session.execute(mention_stmt)
            total_edges = mention_result.scalar() or 0

            return {
                "total_entities": total_entities,
                "orphan_count": orphan_count,
                "duplicate_count": duplicate_count,
                "duplicate_names": duplicate_names,
                "total_edges": total_edges,
            }
    except Exception:
        logger.exception("Failed to get entity health for group_id=%s", group_id)
        raise
