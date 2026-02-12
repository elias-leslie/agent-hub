"""
High-level memory service for Agent Hub.

Wraps Graphiti with application-specific methods for storing and retrieving
conversational memory, voice transcripts, and user preferences.
"""

import logging
from functools import lru_cache
from typing import Any

from . import crud_operations as crud
from . import service_cleanup as cleanup_ops
from . import service_search as search_ops
from . import service_stats as stats_ops
from .graphiti_client import get_graphiti
from .health_operations import check_memory_health
from .list_operations import list_episodes_paginated
from .memory_models import (
    MemoryCategory,
    MemoryCategoryCount,
    MemoryContext,
    MemoryEpisode,
    MemoryListResult,
    MemoryScope,
    MemoryScopeCount,
    MemorySearchResult,
    MemorySource,
    MemoryStats,
)
from .memory_utils import build_group_id, resolve_uuid_prefix

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = [
    "MemoryCategory",
    "MemoryCategoryCount",
    "MemoryContext",
    "MemoryEpisode",
    "MemoryListResult",
    "MemoryScope",
    "MemoryScopeCount",
    "MemorySearchResult",
    "MemoryService",
    "MemorySource",
    "MemoryStats",
    "build_group_id",
    "get_memory_service",
    "resolve_uuid_prefix",
]


class MemoryService:
    """
    High-level memory service for storing and retrieving conversational context.

    Uses Graphiti knowledge graph for semantic memory with episodic recall.
    """

    def __init__(
        self,
        scope: MemoryScope = MemoryScope.GLOBAL,
        scope_id: str | None = None,
        session_id: str | None = None,
    ):
        """
        Initialize memory service.

        Args:
            scope: Memory scope (GLOBAL, PROJECT)
            scope_id: Identifier for the scope (project_id, None for GLOBAL)
            session_id: Session ID for state tracking (optional)
        """
        from .state import GraphitiState

        self.scope = scope
        self.scope_id = scope_id
        # Build group_id for Graphiti using canonical function
        self._group_id = build_group_id(scope, scope_id)
        self._graphiti = get_graphiti()

        # Initialize or load state
        self._state: GraphitiState | None = None
        if session_id:
            # Try to load existing state first
            self._state = GraphitiState.load(session_id)
            if not self._state:
                # Create new state
                self._state = GraphitiState(
                    session_id=session_id,
                    scope=scope,
                    scope_id=scope_id,
                )
                self._state.save()

    async def search(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.0,
        all_groups: bool = False,
    ) -> list[MemorySearchResult]:
        """Semantic search for relevant episodes and facts.

        Args:
            all_groups: If True, search across all groups (for management UI/CLI).
        """
        group_id = None if all_groups else self._group_id
        return await search_ops.semantic_search(
            self._graphiti, group_id, self.scope, query, limit, min_score
        )

    async def text_search(
        self,
        query: str,
        limit: int = 50,
        category: MemoryCategory | None = None,
        all_groups: bool = False,
    ) -> list[MemoryEpisode]:
        """Text-based substring search on episode content."""
        group_id = None if all_groups else self._group_id
        return await search_ops.text_search(
            self._graphiti.driver, group_id, self.scope, self.scope_id, query, limit, category
        )

    async def get_context_for_query(
        self, query: str, max_facts: int = 10, max_entities: int = 5
    ) -> MemoryContext:
        """Get relevant context for a query to inject into LLM prompts."""
        return await search_ops.get_query_context(
            self._graphiti, self._group_id, self.scope, query, max_facts, max_entities
        )

    async def get_patterns_and_gotchas(
        self, query: str, num_results: int = 10, min_score: float = 0.5
    ) -> tuple[list[MemorySearchResult], list[MemorySearchResult]]:
        """Get relevant patterns and gotchas for a query."""
        return await search_ops.get_patterns_gotchas(
            self._graphiti, self._group_id, self.scope, query, num_results, min_score
        )

    async def get_session_history(self, num_sessions: int = 5) -> list[MemoryEpisode]:
        """Get recent session recommendations and insights."""
        return await search_ops.get_history(
            self._graphiti, self._group_id, self.scope, self.scope_id, num_sessions
        )

    async def health_check(self) -> dict[str, Any]:
        """Check memory system health."""
        return await check_memory_health(self._graphiti, self.scope.value, self.scope_id)

    async def delete_episode(self, episode_uuid: str) -> bool:
        """Delete an episode from memory."""
        return await crud.delete_episode(self._graphiti, episode_uuid)

    async def bulk_delete(self, episode_uuids: list[str]) -> dict[str, Any]:
        """Delete multiple episodes from memory."""
        return await crud.bulk_delete_episodes(self._graphiti, episode_uuids)

    async def get_episode(self, episode_uuid: str) -> dict[str, Any] | None:
        """Get detailed information about a single episode including usage stats."""
        return await crud.get_episode_details(self._graphiti.driver, episode_uuid)

    async def batch_get_episodes(self, episode_uuids: list[str]) -> dict[str, dict[str, Any]]:
        """Get multiple episodes in a single query for efficient batch retrieval."""
        return await crud.batch_get_episode_details(self._graphiti.driver, episode_uuids)

    async def cleanup_orphaned_edges(self) -> dict[str, Any]:
        """Clean up edges with stale episode references."""
        return await cleanup_ops.cleanup_orphaned(self._graphiti.driver, self._group_id)

    async def list_episodes(
        self,
        limit: int = 50,
        cursor: str | None = None,
        category: MemoryCategory | None = None,
        all_groups: bool = False,
    ) -> MemoryListResult:
        """List episodes with cursor-based pagination.

        Args:
            limit: Max episodes per page.
            cursor: Timestamp cursor for pagination.
            category: Optional category filter.
            all_groups: If True, list across all groups (for memory page).
        """
        group_id = None if all_groups else self._group_id
        return await list_episodes_paginated(
            self._graphiti.driver,
            group_id,
            self.scope,
            self.scope_id,
            limit,
            cursor,
            category,
        )

    async def get_scope_stats(self) -> list[MemoryScopeCount]:
        """Get episode counts by scope."""
        return await stats_ops.get_all_scope_stats(self._graphiti.driver)

    async def get_stats(self, all_groups: bool = False) -> MemoryStats:
        """Get memory statistics for dashboard KPIs.

        Args:
            all_groups: If True, count across all groups (for memory page).
                       If False, count only this service's group.
        """
        group_id = None if all_groups else self._group_id
        return await stats_ops.get_memory_stats(
            self._graphiti.driver, group_id, self.scope, self.scope_id
        )

    async def cleanup_stale_memories(self, ttl_days: int = 30) -> dict[str, Any]:
        """Clean up memories that haven't been accessed within TTL period."""
        return await cleanup_ops.cleanup_stale(self._graphiti.driver, self._group_id, ttl_days)

    async def close(self) -> None:
        """Close connections."""
        await self._graphiti.close()  # type: ignore[no-untyped-call]


@lru_cache
def get_memory_service(
    scope: MemoryScope = MemoryScope.GLOBAL, scope_id: str | None = None
) -> MemoryService:
    """Get cached memory service instance for a scope."""
    return MemoryService(scope=scope, scope_id=scope_id)
