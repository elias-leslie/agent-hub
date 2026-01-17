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

        return MemoryContext(
            query=query,
            relevant_facts=facts,
            relevant_entities=entities,
            episodes=episodes,
        )

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

    async def close(self) -> None:
        """Close connections."""
        await self._graphiti.close()


@lru_cache
def get_memory_service(group_id: str = "default") -> MemoryService:
    """Get cached memory service instance for a group."""
    return MemoryService(group_id=group_id)
