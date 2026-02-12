"""Memory Episodes - Search handler functions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from app.services.memory import MemoryService
from app.services.memory.service import MemoryCategory, MemoryListResult

if TYPE_CHECKING:
    from .memory_schemas import SearchResponse


async def handle_search_memory(
    query: str,
    memory: MemoryService,
    limit: int,
    min_score: float,
) -> SearchResponse:
    """Semantic search for relevant episodes and facts."""
    from .memory_schemas import SearchResponse

    try:
        results = await memory.search(
            query=query,
            limit=limit,
            min_score=min_score,
            all_groups=True,
        )
        return SearchResponse(
            query=query,
            results=results,
            count=len(results),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {e}") from e


async def handle_text_search_memory(
    query: str,
    memory: MemoryService,
    limit: int,
    category: MemoryCategory | None,
) -> MemoryListResult:
    """Text-based search for episode management UI."""
    try:
        episodes = await memory.text_search(
            query=query,
            limit=limit,
            category=category,
            all_groups=True,
        )
        return MemoryListResult(
            episodes=episodes,
            total=len(episodes),
            cursor=None,
            has_more=False,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Text search failed: {e}") from e


async def handle_get_similar_episodes(
    full_uuid: str,
    memory: MemoryService,
    limit: int,
    min_score: float,
) -> dict[str, Any]:
    """Find episodes with similar content via embedding search."""
    episode = await memory.get_episode(full_uuid)
    if not episode:
        raise HTTPException(status_code=404, detail=f"Episode {full_uuid} not found")

    try:
        results = await memory.search(
            query=episode["content"],
            limit=limit + 1,
            min_score=min_score,
            all_groups=True,
        )
        similar = [
            {
                "uuid": r.uuid,
                "content": r.content[:200],
                "relevance_score": round(r.relevance_score, 3),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in results
            if r.uuid != full_uuid
        ][:limit]

        return {
            "episode_uuid": full_uuid,
            "similar": similar,
            "total": len(similar),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to find similar episodes: {e}") from e
