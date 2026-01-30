"""
High-level memory service for Agent Hub.

Wraps Graphiti with application-specific methods for storing and retrieving
conversational memory, voice transcripts, and user preferences.
"""

import logging
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

from graphiti_core.utils.datetime_utils import utc_now

from .graphiti_client import get_graphiti
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
from .memory_queries import (
    batch_get_episodes,
    cleanup_orphaned_edges,
    cleanup_stale_memories,
    fetch_episodes_filtered,
    get_episode,
)
from .memory_stats import get_scope_stats, get_stats
from .memory_utils import build_group_id, map_episode_type, resolve_uuid_prefix
from .search_operations import (
    get_context_for_query,
    get_patterns_and_gotchas,
    get_session_history,
    search_memory,
)

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
    ) -> list[MemorySearchResult]:
        """
        Search memory for relevant episodes and facts.

        Args:
            query: Search query
            limit: Maximum results to return
            min_score: Minimum relevance score (0-1)

        Returns:
            List of relevant memory results with valid episode UUIDs
        """
        return await search_memory(
            self._graphiti, self._group_id, self.scope, query, limit, min_score
        )

    async def get_context_for_query(
        self,
        query: str,
        max_facts: int = 10,
        max_entities: int = 5,
    ) -> MemoryContext:
        """
        Get relevant context for a query to inject into LLM prompts.

        Args:
            query: The user query to find context for
            max_facts: Maximum facts to include
            max_entities: Maximum entities to include

        Returns:
            MemoryContext with relevant facts, entities, and episodes
        """
        return await get_context_for_query(
            self._graphiti, self._group_id, self.scope, query, max_facts, max_entities
        )

    async def get_patterns_and_gotchas(
        self,
        query: str,
        num_results: int = 10,
        min_score: float = 0.5,
    ) -> tuple[list[MemorySearchResult], list[MemorySearchResult]]:
        """
        Get relevant patterns and gotchas for a query.

        Args:
            query: The query to find patterns and gotchas for
            num_results: Maximum results per category
            min_score: Minimum relevance score (0-1)

        Returns:
            Tuple of (patterns, gotchas) lists
        """
        return await get_patterns_and_gotchas(
            self._graphiti, self._group_id, self.scope, query, num_results, min_score
        )

    async def get_session_history(
        self,
        num_sessions: int = 5,
    ) -> list[MemoryEpisode]:
        """
        Get recent session recommendations and insights.

        Args:
            num_sessions: Maximum number of recent sessions to retrieve from

        Returns:
            List of relevant session episodes
        """
        return await get_session_history(
            self._graphiti, self._group_id, self.scope, self.scope_id, num_sessions
        )

    async def health_check(self) -> dict[str, Any]:
        """
        Check memory system health.

        Returns:
            Health status dict with neo4j and graphiti status
        """
        from typing import cast

        from neo4j import AsyncDriver

        try:
            # Test Neo4j connection - verify_connectivity raises on failure, returns None on success
            driver = cast(AsyncDriver, self._graphiti.driver)
            await driver.verify_connectivity()

            return {
                "status": "healthy",
                "neo4j": "connected",
                "scope": self.scope.value,
                "scope_id": self.scope_id,
            }
        except Exception as e:
            logger.error("Memory health check failed: %s", e)
            return {
                "status": "unhealthy",
                "neo4j": "disconnected",
                "error": str(e),
            }

    async def delete_episode(self, episode_uuid: str) -> bool:
        """
        Delete an episode from memory.

        Args:
            episode_uuid: UUID of the episode to delete

        Returns:
            True if deletion succeeded

        Raises:
            ValueError: If episode not found
        """
        try:
            await self._graphiti.remove_episode(episode_uuid)
            logger.info("Deleted episode: %s", episode_uuid)
            return True
        except Exception as e:
            logger.error("Failed to delete episode %s: %s", episode_uuid, e)
            raise

    async def bulk_delete(self, episode_uuids: list[str]) -> dict[str, Any]:
        """
        Delete multiple episodes from memory.

        Args:
            episode_uuids: List of episode UUIDs to delete

        Returns:
            Dict with deleted count, failed count, and error details
        """
        deleted = 0
        failed = 0
        errors: list[dict[str, str]] = []

        for uuid in episode_uuids:
            try:
                await self._graphiti.remove_episode(uuid)
                deleted += 1
                logger.debug("Bulk deleted episode: %s", uuid)
            except Exception as e:
                failed += 1
                errors.append({"id": uuid, "error": str(e)})
                logger.warning("Bulk delete failed for %s: %s", uuid, e)

        logger.info("Bulk delete complete: %d deleted, %d failed", deleted, failed)
        return {"deleted": deleted, "failed": failed, "errors": errors}

    async def get_episode(self, episode_uuid: str) -> dict[str, Any] | None:
        """
        Get detailed information about a single episode including usage stats.

        Args:
            episode_uuid: UUID of the episode to retrieve

        Returns:
            Dict with episode details and usage stats, or None if not found
        """
        return await get_episode(self._graphiti.driver, episode_uuid)

    async def batch_get_episodes(self, episode_uuids: list[str]) -> dict[str, dict[str, Any]]:
        """
        Get multiple episodes in a single query for efficient batch retrieval.

        Args:
            episode_uuids: List of episode UUIDs to retrieve

        Returns:
            Dict mapping UUID to episode details (missing UUIDs not included)
        """
        return await batch_get_episodes(self._graphiti.driver, episode_uuids)

    async def cleanup_orphaned_edges(self) -> dict[str, Any]:
        """
        Clean up edges with stale episode references.

        Returns:
            Dict with cleanup results: edges_updated, edges_deleted, stale_refs_removed
        """
        return await cleanup_orphaned_edges(self._graphiti.driver, self._group_id)

    async def list_episodes(
        self,
        limit: int = 50,
        cursor: str | None = None,
        category: MemoryCategory | None = None,
    ) -> MemoryListResult:
        """
        List episodes with cursor-based pagination.

        Args:
            limit: Maximum episodes to return
            cursor: ISO timestamp string for cursor (fetch episodes before this time)
            category: Optional category filter

        Returns:
            MemoryListResult with episodes and pagination info
        """
        # Parse cursor as datetime or use now
        if cursor:
            try:
                reference_time = datetime.fromisoformat(cursor)
                # Subtract 1 microsecond to exclude the episode at exactly cursor time.
                reference_time = reference_time - timedelta(microseconds=1)
            except ValueError:
                reference_time = utc_now()
        else:
            reference_time = utc_now()

        # Always use our custom query to get usage stats (category=None for unfiltered)
        episodes_raw, has_more = await fetch_episodes_filtered(
            self._graphiti.driver, self._group_id, limit, reference_time, category
        )

        # Convert to MemoryEpisode objects
        episodes: list[MemoryEpisode] = []
        for ep in episodes_raw:
            # Use injection_tier as source of truth; default to REFERENCE for Graphiti API results
            tier = getattr(ep, "injection_tier", None)
            if tier == "mandate":
                cat = MemoryCategory.MANDATE
            elif tier == "guardrail":
                cat = MemoryCategory.GUARDRAIL
            else:
                cat = MemoryCategory.REFERENCE

            episodes.append(
                MemoryEpisode(
                    uuid=ep.uuid,
                    name=ep.name,
                    content=ep.content,
                    source=map_episode_type(ep.source),
                    category=cat,
                    scope=self.scope,
                    scope_id=self.scope_id,
                    source_description=ep.source_description,
                    created_at=ep.created_at,
                    valid_at=ep.valid_at,
                    entities=ep.entity_edges,  # Edge UUIDs, could be enhanced
                    summary=getattr(ep, "summary", None),
                    loaded_count=getattr(ep, "loaded_count", None),
                    referenced_count=getattr(ep, "referenced_count", None),
                    helpful_count=getattr(ep, "helpful_count", None),
                    harmful_count=getattr(ep, "harmful_count", None),
                    utility_score=getattr(ep, "utility_score", None),
                )
            )

        # Calculate cursor for next page
        next_cursor = None
        if episodes and has_more:
            # Use the valid_at of the last episode as cursor
            next_cursor = episodes[-1].valid_at.isoformat()

        return MemoryListResult(
            episodes=episodes,
            total=len(episodes),
            cursor=next_cursor,
            has_more=has_more,
        )

    async def get_scope_stats(self) -> list[MemoryScopeCount]:
        """
        Get episode counts by scope.

        Returns:
            List of scopes with their episode counts
        """
        return await get_scope_stats(self._graphiti.driver)

    async def get_stats(self) -> MemoryStats:
        """
        Get memory statistics for dashboard KPIs.

        Returns:
            MemoryStats with total count, category/scope breakdowns, and last updated time
        """
        return await get_stats(
            self._graphiti.driver, self._group_id, self.scope, self.scope_id
        )

    async def cleanup_stale_memories(self, ttl_days: int = 30) -> dict[str, Any]:
        """
        Clean up memories that haven't been accessed within TTL period.

        Args:
            ttl_days: Days without access before memory is considered stale

        Returns:
            Dict with cleanup results: deleted count, skipped, and reason
        """
        return await cleanup_stale_memories(self._graphiti.driver, self._group_id, ttl_days)

    async def close(self) -> None:
        """Close connections."""
        await self._graphiti.close()  # type: ignore[no-untyped-call]


@lru_cache
def get_memory_service(
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> MemoryService:
    """Get cached memory service instance for a scope."""
    return MemoryService(scope=scope, scope_id=scope_id)
