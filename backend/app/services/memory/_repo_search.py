"""Semantic search sub-repository for memories."""

from __future__ import annotations

import uuid as _uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session


def _build_semantic_params(
    *,
    vec_str: str,
    status: str,
    limit: int,
    scope: str | None,
    group_id: str | None,
    tier: int | str | None,
    memory_type: str | None,
    min_score: float,
    exclude_ids: list[_uuid.UUID] | None,
) -> tuple[list[str], dict[str, Any]]:
    """Build WHERE conditions and params for semantic search."""
    conditions = ["status = :status", "embedding IS NOT NULL"]
    params: dict[str, Any] = {"status": status, "vec": vec_str, "limit": limit}

    if scope:
        conditions.append("scope = :scope")
        params["scope"] = scope
    if group_id:
        conditions.append("group_id = :group_id")
        params["group_id"] = group_id
    if tier is not None:
        conditions.append("tier = :tier")
        params["tier"] = tier
    if memory_type:
        conditions.append("memory_type = :memory_type")
        params["memory_type"] = memory_type
    if min_score > 0:
        conditions.append("(1 - (embedding <=> CAST(:vec AS vector))) >= :min_score")
        params["min_score"] = min_score
    if exclude_ids:
        conditions.append("id NOT IN :exclude_ids")
        params["exclude_ids"] = tuple(exclude_ids)

    return conditions, params


class SearchRepository:
    """Handles vector semantic search for memories."""

    async def semantic_search(
        self,
        query_embedding: list[float],
        *,
        scope: str | None = None,
        group_id: str | None = None,
        tier: int | str | None = None,
        memory_type: str | None = None,
        status: str = "active",
        limit: int = 10,
        min_score: float = 0.0,
        exclude_ids: list[_uuid.UUID] | None = None,
        db: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search using pgvector cosine similarity.

        Returns list of dicts with memory data + relevance_score.
        """
        vec_str = "[" + ",".join(str(f) for f in query_embedding) + "]"
        conditions, params = _build_semantic_params(
            vec_str=vec_str,
            status=status,
            limit=limit,
            scope=scope,
            group_id=group_id,
            tier=tier,
            memory_type=memory_type,
            min_score=min_score,
            exclude_ids=exclude_ids,
        )
        where = " AND ".join(conditions)
        sql = text(f"""
            SELECT id, content, name, summary, memory_type, scope, scope_id,
                   group_id, source, source_description, tags,
                   tier, pinned, auto_inject, display_order,
                   trigger_task_types, trigger_phases,
                   loaded_count, referenced_count, helpful_count, harmful_count,
                   status, token_count, metadata, valid_at,
                   created_at, updated_at, last_accessed_at,
                   context_kind, applicability,
                   (1 - (embedding <=> CAST(:vec AS vector))) AS relevance_score
            FROM memories
            WHERE {where}
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT :limit
        """)

        if db:
            result = await db.execute(sql, params)
            rows = result.mappings().all()
        else:
            async with async_session() as session:
                result = await session.execute(sql, params)
                rows = result.mappings().all()

        return [dict(row) for row in rows]
