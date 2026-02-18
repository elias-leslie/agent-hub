"""Mixin classes for MemoryService to keep each class under 10 methods."""

from typing import Any

from . import crud_operations as crud
from . import service_cleanup as cleanup_ops
from . import service_search as search_ops
from .memory_models import (
    MemoryCategory,
    MemoryContext,
    MemoryEpisode,
    MemorySearchResult,
)


class _ServiceSearchMixin:
    """Search and context retrieval methods for MemoryService."""

    async def search(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.0,
        all_groups: bool = False,
    ) -> list[MemorySearchResult]:
        """Semantic search for relevant episodes and facts."""
        group_id = None if all_groups else self._group_id  # type: ignore[attr-defined]
        return await search_ops.semantic_search(
            self._graphiti, group_id, self.scope, query, limit, min_score  # type: ignore[attr-defined]
        )

    async def text_search(
        self,
        query: str,
        limit: int = 50,
        category: MemoryCategory | None = None,
        all_groups: bool = False,
    ) -> list[MemoryEpisode]:
        """Text-based substring search on episode content."""
        group_id = None if all_groups else self._group_id  # type: ignore[attr-defined]
        return await search_ops.text_search(
            self._graphiti.driver, group_id, self.scope, self.scope_id, query, limit, category  # type: ignore[attr-defined]
        )

    async def get_context_for_query(
        self, query: str, max_facts: int = 10, max_entities: int = 5
    ) -> MemoryContext:
        """Get relevant context for a query to inject into LLM prompts."""
        return await search_ops.get_query_context(
            self._graphiti, self._group_id, self.scope, query, max_facts, max_entities  # type: ignore[attr-defined]
        )

    async def get_patterns_and_gotchas(
        self, query: str, num_results: int = 10, min_score: float = 0.5
    ) -> tuple[list[MemorySearchResult], list[MemorySearchResult]]:
        """Get relevant patterns and gotchas for a query."""
        return await search_ops.get_patterns_gotchas(
            self._graphiti, self._group_id, self.scope, query, num_results, min_score  # type: ignore[attr-defined]
        )

    async def get_session_history(self, num_sessions: int = 5) -> list[MemoryEpisode]:
        """Get recent session recommendations and insights."""
        return await search_ops.get_history(
            self._graphiti, self._group_id, self.scope, self.scope_id, num_sessions  # type: ignore[attr-defined]
        )


class _ServiceCrudMixin:
    """CRUD and cleanup methods for MemoryService."""

    async def delete_episode(self, episode_uuid: str) -> bool:
        """Delete an episode from memory."""
        return await crud.delete_episode(self._graphiti, episode_uuid)  # type: ignore[attr-defined]

    async def bulk_delete(self, episode_uuids: list[str]) -> dict[str, Any]:
        """Delete multiple episodes from memory."""
        return await crud.bulk_delete_episodes(self._graphiti, episode_uuids)  # type: ignore[attr-defined]

    async def get_episode(self, episode_uuid: str) -> dict[str, Any] | None:
        """Get detailed information about a single episode including usage stats."""
        return await crud.get_episode_details(self._graphiti.driver, episode_uuid)  # type: ignore[attr-defined]

    async def batch_get_episodes(self, episode_uuids: list[str]) -> dict[str, dict[str, Any]]:
        """Get multiple episodes in a single query for efficient batch retrieval."""
        return await crud.batch_get_episode_details(self._graphiti.driver, episode_uuids)  # type: ignore[attr-defined]

    async def cleanup_orphaned_edges(self) -> dict[str, Any]:
        """Clean up edges with stale episode references."""
        return await cleanup_ops.cleanup_orphaned(self._graphiti.driver, self._group_id)  # type: ignore[attr-defined]

    async def cleanup_stale_memories(self, ttl_days: int = 30) -> dict[str, Any]:
        """Clean up memories that haven't been accessed within TTL period."""
        return await cleanup_ops.cleanup_stale(self._graphiti.driver, self._group_id, ttl_days)  # type: ignore[attr-defined]
