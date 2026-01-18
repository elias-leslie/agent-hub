"""
High-level memory service for Agent Hub.

Wraps Graphiti with application-specific methods for storing and retrieving
conversational memory, voice transcripts, and user preferences.
"""

import logging
from datetime import datetime
from enum import Enum
from functools import lru_cache
from typing import Any

from graphiti_core.nodes import EpisodeType
from pydantic import BaseModel

from .graphiti_client import get_graphiti

logger = logging.getLogger(__name__)


class MemorySource(str, Enum):
    """Source types for memory episodes."""

    CHAT = "chat"
    VOICE = "voice"
    SYSTEM = "system"


class MemorySearchResult(BaseModel):
    """Search result from memory system."""

    uuid: str
    content: str
    source: MemorySource
    relevance_score: float
    created_at: datetime
    facts: list[str] = []


class MemoryContext(BaseModel):
    """Context retrieved for a query."""

    query: str
    relevant_facts: list[str]
    relevant_entities: list[str]
    episodes: list[MemorySearchResult]


class MemoryCategory(str, Enum):
    """Category types for memory episodes (following Auto-Claude patterns)."""

    SESSION_INSIGHT = "session_insight"
    CODEBASE_DISCOVERY = "codebase_discovery"
    PATTERN = "pattern"
    GOTCHA = "gotcha"
    TASK_OUTCOME = "task_outcome"
    QA_RESULT = "qa_result"
    HISTORICAL_CONTEXT = "historical_context"
    UNCATEGORIZED = "uncategorized"


class MemoryEpisode(BaseModel):
    """Full episode details for listing."""

    uuid: str
    name: str
    content: str
    source: MemorySource
    category: MemoryCategory
    source_description: str
    created_at: datetime
    valid_at: datetime
    entities: list[str] = []


class MemoryListResult(BaseModel):
    """Paginated list of episodes."""

    episodes: list[MemoryEpisode]
    total: int
    cursor: str | None = None  # Timestamp ISO string for next page
    has_more: bool


class MemoryCategoryCount(BaseModel):
    """Count for a single category."""

    category: MemoryCategory
    count: int


class MemoryStats(BaseModel):
    """Memory statistics for dashboard KPIs."""

    total: int
    by_category: list[MemoryCategoryCount]
    last_updated: datetime | None
    group_id: str


class MemoryGroup(BaseModel):
    """Memory group with episode count."""

    group_id: str
    episode_count: int


class MemoryService:
    """
    High-level memory service for storing and retrieving conversational context.

    Uses Graphiti knowledge graph for semantic memory with episodic recall.
    """

    def __init__(self, group_id: str = "default"):
        """
        Initialize memory service.

        Args:
            group_id: Namespace for memory isolation (e.g., user ID, session ID)
        """
        self.group_id = group_id
        self._graphiti = get_graphiti()

    async def add_episode(
        self,
        content: str,
        source: MemorySource = MemorySource.CHAT,
        source_description: str | None = None,
        reference_time: datetime | None = None,
    ) -> str:
        """
        Add an episode to memory.

        Args:
            content: The content to remember (conversation turn, transcript, etc.)
            source: Source type of the episode
            source_description: Human-readable description of the source
            reference_time: When the episode occurred (defaults to now)

        Returns:
            UUID of the created episode
        """
        reference_time = reference_time or datetime.now()
        source_description = source_description or f"{source.value} interaction"

        result = await self._graphiti.add_episode(
            name=f"{source.value}_{reference_time.isoformat()}",
            episode_body=content,
            source=EpisodeType.message,
            source_description=source_description,
            reference_time=reference_time,
            group_id=self.group_id,
        )

        logger.info(
            "Added episode: %s entities, %s edges",
            len(result.nodes),
            len(result.edges),
        )

        return result.episode.uuid

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
            List of relevant memory results
        """
        # Graphiti.search() returns list[EntityEdge] directly, not a SearchResults object
        edges = await self._graphiti.search(
            query=query,
            group_ids=[self.group_id],
            num_results=limit,
        )

        search_results = []
        edge_uuids = []
        for edge in edges:
            # Extract facts from edge relationships
            facts = [edge.fact] if hasattr(edge, "fact") and edge.fact else []

            result = MemorySearchResult(
                uuid=edge.uuid,
                content=edge.fact or "",
                source=MemorySource.CHAT,  # Default, could be enriched
                relevance_score=getattr(edge, "score", 1.0),
                created_at=edge.created_at,
                facts=facts,
            )

            if result.relevance_score >= min_score:
                search_results.append(result)
                edge_uuids.append(edge.uuid)

        # Update access timestamps for returned edges
        if edge_uuids:
            await self._update_access_time(edge_uuids)

        return search_results[:limit]

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
        # Graphiti.search() returns list[EntityEdge] directly
        edges = await self._graphiti.search(
            query=query,
            group_ids=[self.group_id],
            num_results=max_facts + max_entities,
        )

        # Extract unique facts from edges
        facts = []
        for edge in edges[:max_facts]:
            if hasattr(edge, "fact") and edge.fact:
                facts.append(edge.fact)

        # Extract unique entities from edge source/target nodes
        # EntityEdge has source_node and target_node attributes
        entities = []
        seen_names: set[str] = set()
        for edge in edges[:max_entities]:
            # Try to get entity names from edge endpoints
            source_name = getattr(edge, "source_node_name", None)
            target_name = getattr(edge, "target_node_name", None)
            for name in [source_name, target_name]:
                if name and name not in seen_names:
                    entities.append(name)
                    seen_names.add(name)

        # Build episode results from edges
        episodes = []
        for edge in edges[:5]:
            episodes.append(
                MemorySearchResult(
                    uuid=edge.uuid,
                    content=edge.fact or "",
                    source=MemorySource.CHAT,
                    relevance_score=getattr(edge, "score", 1.0),
                    created_at=edge.created_at,
                    facts=[edge.fact] if edge.fact else [],
                )
            )

        # Update access timestamps for accessed edges
        if edges:
            await self._update_access_time([e.uuid for e in edges])

        return MemoryContext(
            query=query,
            relevant_facts=facts,
            relevant_entities=entities,
            episodes=episodes,
        )

    async def _update_access_time(self, uuids: list[str]) -> None:
        """
        Update last_accessed_at timestamp for accessed memory items.

        Args:
            uuids: List of edge/episode UUIDs that were accessed
        """
        if not uuids:
            return

        driver = self._graphiti.driver
        now = datetime.now().isoformat()

        # Update last_accessed_at on EntityEdge nodes
        query = """
        UNWIND $uuids AS uuid
        MATCH (e:EntityEdge {uuid: uuid})
        SET e.last_accessed_at = datetime($now)
        """

        try:
            await driver.execute_query(query, uuids=uuids, now=now)
            logger.debug("Updated access time for %d items", len(uuids))
        except Exception as e:
            # Don't fail the request if access tracking fails
            logger.warning("Failed to update access time: %s", e)

    async def health_check(self) -> dict[str, Any]:
        """
        Check memory system health.

        Returns:
            Health status dict with neo4j and graphiti status
        """
        try:
            # Test Neo4j connection - health_check raises on failure, returns None on success
            driver = self._graphiti.driver
            await driver.health_check()

            return {
                "status": "healthy",
                "neo4j": "connected",
                "group_id": self.group_id,
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

        Uses Graphiti's remove_episode which:
        - Deletes edges where this episode is the first reference
        - Deletes nodes only mentioned in this episode
        - Deletes the episode itself

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
            except ValueError:
                reference_time = datetime.now()
        else:
            reference_time = datetime.now()

        # Fetch one extra to check if there are more
        episodes_raw = await self._graphiti.retrieve_episodes(
            reference_time=reference_time,
            last_n=limit + 1,
            group_ids=[self.group_id],
        )

        has_more = len(episodes_raw) > limit
        episodes_raw = episodes_raw[:limit]

        # Convert to MemoryEpisode objects
        episodes: list[MemoryEpisode] = []
        for ep in episodes_raw:
            # Infer category from source_description or name
            cat = self._infer_category(ep.source_description, ep.name)

            # Filter by category if specified
            if category and cat != category:
                continue

            episodes.append(
                MemoryEpisode(
                    uuid=ep.uuid,
                    name=ep.name,
                    content=ep.content,
                    source=self._map_episode_type(ep.source),
                    category=cat,
                    source_description=ep.source_description,
                    created_at=ep.created_at,
                    valid_at=ep.valid_at,
                    entities=ep.entity_edges,  # Edge UUIDs, could be enhanced
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

    def _infer_category(self, source_desc: str, name: str) -> MemoryCategory:
        """Infer category from source description or name."""
        combined = f"{source_desc} {name}".lower()

        if "session" in combined or "insight" in combined:
            return MemoryCategory.SESSION_INSIGHT
        elif "codebase" in combined or "discovery" in combined:
            return MemoryCategory.CODEBASE_DISCOVERY
        elif "pattern" in combined:
            return MemoryCategory.PATTERN
        elif "gotcha" in combined or "pitfall" in combined:
            return MemoryCategory.GOTCHA
        elif "task" in combined or "outcome" in combined:
            return MemoryCategory.TASK_OUTCOME
        elif "qa" in combined or "test" in combined:
            return MemoryCategory.QA_RESULT
        elif "history" in combined or "context" in combined:
            return MemoryCategory.HISTORICAL_CONTEXT
        else:
            return MemoryCategory.UNCATEGORIZED

    def _map_episode_type(self, ep_type: EpisodeType) -> MemorySource:
        """Map Graphiti EpisodeType to our MemorySource."""
        # EpisodeType is message, json, text
        # Default to CHAT for message type
        if ep_type == EpisodeType.message:
            return MemorySource.CHAT
        else:
            return MemorySource.SYSTEM

    async def get_groups(self) -> list[MemoryGroup]:
        """
        Get all available memory groups with episode counts.

        Returns list of groups sorted by episode count descending.
        """
        driver = self._graphiti.driver

        # Query for distinct group_ids and counts
        query = """
        MATCH (e:Episodic)
        RETURN e.group_id AS group_id, count(e) AS count
        ORDER BY count DESC
        """

        try:
            records, _, _ = await driver.execute_query(query)
            return [
                MemoryGroup(
                    group_id=record["group_id"] or "default",
                    episode_count=record["count"],
                )
                for record in records
            ]
        except Exception as e:
            logger.error("Failed to get groups: %s", e)
            # Return at least the current group
            return [MemoryGroup(group_id=self.group_id, episode_count=0)]

    async def get_stats(self) -> MemoryStats:
        """
        Get memory statistics for dashboard KPIs.

        Returns total count, breakdown by category, and last updated time.
        """
        # Fetch all episodes (up to a reasonable limit for stats)
        # In production, this would be a direct Cypher aggregation query
        episodes_raw = await self._graphiti.retrieve_episodes(
            reference_time=datetime.now(),
            last_n=1000,  # Reasonable limit for stats
            group_ids=[self.group_id],
        )

        # Count by category
        category_counts: dict[MemoryCategory, int] = {}
        last_updated: datetime | None = None

        for ep in episodes_raw:
            cat = self._infer_category(ep.source_description, ep.name)
            category_counts[cat] = category_counts.get(cat, 0) + 1

            # Track most recent episode
            if last_updated is None or ep.created_at > last_updated:
                last_updated = ep.created_at

        return MemoryStats(
            total=len(episodes_raw),
            by_category=[
                MemoryCategoryCount(category=cat, count=count)
                for cat, count in sorted(category_counts.items(), key=lambda x: x[1], reverse=True)
            ],
            last_updated=last_updated,
            group_id=self.group_id,
        )

    async def cleanup_stale_memories(
        self,
        ttl_days: int = 30,
    ) -> dict[str, Any]:
        """
        Clean up memories that haven't been accessed within TTL period.

        Implements system activity safeguard: if the system itself hasn't been
        active for 30+ days (no new episodes), cleanup is skipped to prevent
        accidental mass deletion when system resumes.

        Args:
            ttl_days: Days without access before memory is considered stale

        Returns:
            Dict with cleanup results: deleted count, skipped, and reason
        """
        driver = self._graphiti.driver
        now = datetime.now()

        # First, check system activity - when was the last episode created?
        activity_query = """
        MATCH (e:Episodic {group_id: $group_id})
        RETURN max(e.created_at) AS last_activity
        """

        try:
            records, _, _ = await driver.execute_query(
                activity_query,
                group_id=self.group_id,
            )

            if records and records[0]["last_activity"]:
                last_activity = records[0]["last_activity"]
                # Neo4j returns datetime as neo4j.time.DateTime, convert to Python
                if hasattr(last_activity, "to_native"):
                    last_activity = last_activity.to_native()

                days_inactive = (now - last_activity).days

                if days_inactive >= ttl_days:
                    logger.warning(
                        "System inactive for %d days, skipping cleanup to prevent mass deletion",
                        days_inactive,
                    )
                    return {
                        "deleted": 0,
                        "skipped": True,
                        "reason": f"System inactive for {days_inactive} days - cleanup skipped as safeguard",
                    }
            else:
                # No episodes found
                return {
                    "deleted": 0,
                    "skipped": True,
                    "reason": "No episodes found in group",
                }

        except Exception as e:
            logger.error("Failed to check system activity: %s", e)
            return {
                "deleted": 0,
                "skipped": True,
                "reason": f"Activity check failed: {e}",
            }

        # Find and delete stale edges (not accessed within TTL)
        cutoff = now - __import__("datetime").timedelta(days=ttl_days)

        cleanup_query = """
        MATCH (e:EntityEdge {group_id: $group_id})
        WHERE e.last_accessed_at IS NOT NULL
          AND e.last_accessed_at < datetime($cutoff)
        WITH e LIMIT 100
        DETACH DELETE e
        RETURN count(e) AS deleted
        """

        try:
            records, _, _ = await driver.execute_query(
                cleanup_query,
                group_id=self.group_id,
                cutoff=cutoff.isoformat(),
            )

            deleted = records[0]["deleted"] if records else 0
            logger.info(
                "Cleanup complete for group %s: %d stale memories deleted",
                self.group_id,
                deleted,
            )

            return {
                "deleted": deleted,
                "skipped": False,
                "reason": None,
            }

        except Exception as e:
            logger.error("Cleanup failed: %s", e)
            return {
                "deleted": 0,
                "skipped": True,
                "reason": f"Cleanup query failed: {e}",
            }

    async def close(self) -> None:
        """Close connections."""
        await self._graphiti.close()


@lru_cache
def get_memory_service(group_id: str = "default") -> MemoryService:
    """Get cached memory service instance for a group."""
    return MemoryService(group_id=group_id)
