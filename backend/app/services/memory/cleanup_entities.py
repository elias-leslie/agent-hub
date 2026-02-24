"""
Entity cleanup operations.

Handles orphaned entity deletion and duplicate entity consolidation
using PostgreSQL via SQLAlchemy (replaces Neo4j Cypher queries).
"""

import logging
from typing import Any

from sqlalchemy import delete, func, select, update

from app.db import async_session
from app.models.memory_unified import MemoryEntity, MemoryEntityMention

logger = logging.getLogger(__name__)


async def cleanup_orphaned_entities(
    driver: Any = None,
    group_id: str = "",
) -> dict[str, Any]:
    """Delete MemoryEntity rows with zero mentions.

    These accumulate when memories are deleted but their extracted entities remain.

    Args:
        driver: Ignored (kept for backward-compat signature).
        group_id: Ignored in PostgreSQL mode (entities are scoped, not grouped).

    Returns:
        Dict with entities_deleted count.
    """
    try:
        async with async_session() as session:
            # Find entity IDs that have no rows in the mentions join table
            mentioned_ids = select(MemoryEntityMention.entity_id).distinct()
            stmt = delete(MemoryEntity).where(
                MemoryEntity.id.not_in(mentioned_ids),
            )
            result = await session.execute(stmt)
            await session.commit()

            deleted = result.rowcount  # type: ignore[union-attr]
            if deleted:
                logger.info(
                    "Orphaned entity cleanup: %d entities deleted",
                    deleted,
                )
            return {"entities_deleted": deleted}

    except Exception as e:
        logger.error("Orphaned entity cleanup failed: %s", e)
        return {"entities_deleted": 0, "error": str(e)}


async def consolidate_duplicate_entities(
    driver: Any = None,
    group_id: str = "",
) -> dict[str, Any]:
    """Merge duplicate MemoryEntity rows (same name + scope) into one.

    For each set of duplicates:
    1. Keep the entity with the lowest created_at (oldest).
    2. Re-point all MemoryEntityMention rows from duplicates to the kept entity.
    3. Sum mention_count onto the kept entity.
    4. Delete the duplicate entity rows.

    Args:
        driver: Ignored (kept for backward-compat signature).
        group_id: Ignored in PostgreSQL mode.

    Returns:
        Dict with duplicates_found and entities_merged counts.
    """
    try:
        async with async_session() as session:
            # Find (name, scope) combos that appear more than once
            dup_stmt = (
                select(
                    MemoryEntity.name,
                    MemoryEntity.scope,
                    func.count(MemoryEntity.id).label("cnt"),
                )
                .group_by(MemoryEntity.name, MemoryEntity.scope)
                .having(func.count(MemoryEntity.id) > 1)
            )
            dup_rows = (await session.execute(dup_stmt)).all()

            if not dup_rows:
                return {"duplicates_found": 0, "entities_merged": 0}

            total_merged = 0

            for name, scope, cnt in dup_rows:
                # Fetch all entities for this (name, scope) ordered by created_at
                entities_stmt = (
                    select(MemoryEntity)
                    .where(
                        MemoryEntity.name == name,
                        MemoryEntity.scope == scope,
                    )
                    .order_by(MemoryEntity.created_at.asc())
                )
                entities = list(
                    (await session.execute(entities_stmt)).scalars().all()
                )
                if len(entities) < 2:
                    continue

                keep = entities[0]
                duplicates = entities[1:]
                dup_ids = [e.id for e in duplicates]

                # Re-point mentions from duplicates to kept entity.
                # Use ON CONFLICT-safe approach: delete mentions that would
                # conflict (same memory_id already linked to keep), then update
                # the rest.
                existing_memory_ids_stmt = select(
                    MemoryEntityMention.memory_id
                ).where(MemoryEntityMention.entity_id == keep.id)
                existing_memory_ids = set(
                    (await session.execute(existing_memory_ids_stmt))
                    .scalars()
                    .all()
                )

                # Delete conflicting mentions (already linked to keep)
                if existing_memory_ids:
                    del_conflict = delete(MemoryEntityMention).where(
                        MemoryEntityMention.entity_id.in_(dup_ids),
                        MemoryEntityMention.memory_id.in_(existing_memory_ids),
                    )
                    await session.execute(del_conflict)

                # Re-point remaining mentions to kept entity
                repoint_stmt = (
                    update(MemoryEntityMention)
                    .where(MemoryEntityMention.entity_id.in_(dup_ids))
                    .values(entity_id=keep.id)
                )
                await session.execute(repoint_stmt)

                # Sum mention counts
                total_mentions = keep.mention_count + sum(
                    e.mention_count for e in duplicates
                )
                keep.mention_count = total_mentions

                # Delete duplicate entities
                del_dup = delete(MemoryEntity).where(
                    MemoryEntity.id.in_(dup_ids)
                )
                await session.execute(del_dup)

                total_merged += len(duplicates)

            await session.commit()

            duplicates_found = len(dup_rows)
            if total_merged:
                logger.info(
                    "Entity consolidation: %d duplicate names, %d entities merged",
                    duplicates_found,
                    total_merged,
                )
            return {
                "duplicates_found": duplicates_found,
                "entities_merged": total_merged,
            }

    except Exception as e:
        logger.error("Entity consolidation failed: %s", e)
        return {"duplicates_found": 0, "entities_merged": 0, "error": str(e)}
