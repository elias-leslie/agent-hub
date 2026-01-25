"""
High-level memory service for Agent Hub.

Wraps Graphiti with application-specific methods for storing and retrieving
conversational memory, voice transcripts, and user preferences.
"""

import logging
from datetime import datetime, timedelta
from enum import Enum
from functools import lru_cache
from typing import Any

from graphiti_core.nodes import EpisodeType
from graphiti_core.utils.datetime_utils import utc_now
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
    scope: "MemoryScope | None" = None
    category: "MemoryCategory | None" = None


class MemoryContext(BaseModel):
    """Context retrieved for a query."""

    query: str
    relevant_facts: list[str]
    relevant_entities: list[str]
    episodes: list[MemorySearchResult]


class MemoryScope(str, Enum):
    """Scope for memory episodes - determines visibility and retrieval context."""

    GLOBAL = "global"  # System-wide learnings (coding standards, common gotchas)
    PROJECT = "project"  # Project-specific patterns and knowledge


def build_group_id(scope: MemoryScope, scope_id: str | None = None) -> str:
    """
    Build Graphiti group_id from scope and scope_id.

    This is the canonical implementation - use this instead of duplicating logic.
    Graphiti only allows alphanumeric, dashes, and underscores in group_id.

    Args:
        scope: Memory scope (GLOBAL, PROJECT)
        scope_id: Identifier for the scope (project_id)

    Returns:
        Sanitized group_id string for Graphiti
    """
    if scope == MemoryScope.GLOBAL:
        return "global"

    # Sanitize scope_id: replace invalid characters with dashes
    safe_id = (scope_id or "default").replace(":", "-").replace("/", "-")

    if scope == MemoryScope.PROJECT:
        return f"project-{safe_id}"

    # Should not reach here with current enum values
    raise ValueError(f"Unknown scope: {scope}")


class MemoryCategory(str, Enum):
    """Category types for memory episodes (consolidated 6-category taxonomy)."""

    CODING_STANDARD = "coding_standard"  # Best practices, style guides, patterns to follow
    TROUBLESHOOTING_GUIDE = "troubleshooting_guide"  # Gotchas, pitfalls, known issues
    SYSTEM_DESIGN = "system_design"  # Architecture decisions, design patterns
    OPERATIONAL_CONTEXT = "operational_context"  # Environment setup, deployment, runtime
    DOMAIN_KNOWLEDGE = "domain_knowledge"  # Business logic, domain-specific concepts
    ACTIVE_STATE = "active_state"  # Current task state, in-progress work


class MemoryEpisode(BaseModel):
    """Full episode details for listing."""

    uuid: str
    name: str
    content: str
    source: MemorySource
    category: MemoryCategory
    scope: MemoryScope = MemoryScope.GLOBAL
    scope_id: str | None = None  # project_id or task_id depending on scope
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


class MemoryScopeCount(BaseModel):
    """Count for a single scope."""

    scope: MemoryScope
    count: int


class MemoryStats(BaseModel):
    """Memory statistics for dashboard KPIs."""

    total: int
    by_category: list[MemoryCategoryCount]
    by_scope: list[MemoryScopeCount] = []
    last_updated: datetime | None
    scope: MemoryScope = MemoryScope.GLOBAL
    scope_id: str | None = None


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
            List of relevant memory results
        """
        # Graphiti.search() returns list[EntityEdge] directly, not a SearchResults object
        edges = await self._graphiti.search(
            query=query,
            group_ids=[self._group_id],
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
                scope=self.scope,
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
            group_ids=[self._group_id],
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
                    scope=self.scope,
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

    async def get_patterns_and_gotchas(
        self,
        query: str,
        num_results: int = 10,
        min_score: float = 0.5,
    ) -> tuple[list[MemorySearchResult], list[MemorySearchResult]]:
        """
        Get relevant patterns and gotchas for a query.

        Uses type-prefixed queries to find:
        - Patterns: coding standards, best practices (CODING_STANDARD category)
        - Gotchas: troubleshooting guides, known issues (TROUBLESHOOTING_GUIDE category)

        Args:
            query: The query to find patterns and gotchas for
            num_results: Maximum results per category
            min_score: Minimum relevance score (0-1)

        Returns:
            Tuple of (patterns, gotchas) lists
        """
        # Search for coding standards/patterns
        pattern_query = f"coding standard pattern: {query}"
        pattern_edges = await self._graphiti.search(
            query=pattern_query,
            group_ids=[self._group_id],
            num_results=num_results * 2,  # Fetch more to filter
        )

        # Search for troubleshooting/gotchas
        gotcha_query = f"troubleshooting gotcha pitfall: {query}"
        gotcha_edges = await self._graphiti.search(
            query=gotcha_query,
            group_ids=[self._group_id],
            num_results=num_results * 2,
        )

        # Build results and filter by category
        patterns: list[MemorySearchResult] = []
        gotchas: list[MemorySearchResult] = []
        all_uuids: list[str] = []

        for edge in pattern_edges:
            score = getattr(edge, "score", 1.0)
            if score < min_score:
                continue

            # Infer category to filter
            source_desc = getattr(edge, "source_description", "") or ""
            name = getattr(edge, "name", "") or ""
            category = self._infer_category(source_desc, name)

            if category == MemoryCategory.CODING_STANDARD:
                patterns.append(
                    MemorySearchResult(
                        uuid=edge.uuid,
                        content=edge.fact or "",
                        source=MemorySource.CHAT,
                        relevance_score=score,
                        created_at=edge.created_at,
                        facts=[edge.fact] if edge.fact else [],
                        scope=self.scope,
                        category=category,
                    )
                )
                all_uuids.append(edge.uuid)

            if len(patterns) >= num_results:
                break

        for edge in gotcha_edges:
            score = getattr(edge, "score", 1.0)
            if score < min_score:
                continue

            source_desc = getattr(edge, "source_description", "") or ""
            name = getattr(edge, "name", "") or ""
            category = self._infer_category(source_desc, name)

            if category == MemoryCategory.TROUBLESHOOTING_GUIDE:
                gotchas.append(
                    MemorySearchResult(
                        uuid=edge.uuid,
                        content=edge.fact or "",
                        source=MemorySource.CHAT,
                        relevance_score=score,
                        created_at=edge.created_at,
                        facts=[edge.fact] if edge.fact else [],
                        scope=self.scope,
                        category=category,
                    )
                )
                all_uuids.append(edge.uuid)

            if len(gotchas) >= num_results:
                break

        # Update access timestamps
        if all_uuids:
            await self._update_access_time(all_uuids)

        return patterns, gotchas

    async def get_session_history(
        self,
        num_sessions: int = 5,
    ) -> list[MemoryEpisode]:
        """
        Get recent session recommendations and insights.

        Retrieves episodes from recent sessions that contain insights,
        recommendations, or learnings that may be relevant for the current session.

        Args:
            num_sessions: Maximum number of recent sessions to retrieve from

        Returns:
            List of relevant session episodes
        """
        episodes_raw = await self._graphiti.retrieve_episodes(
            reference_time=utc_now(),
            last_n=num_sessions * 10,  # Fetch more to filter for relevant types
            group_ids=[self._group_id],
        )

        # Filter for session-relevant categories
        relevant_categories = {
            MemoryCategory.ACTIVE_STATE,
            MemoryCategory.DOMAIN_KNOWLEDGE,
            MemoryCategory.TROUBLESHOOTING_GUIDE,
        }

        episodes: list[MemoryEpisode] = []
        for ep in episodes_raw:
            cat = self._infer_category(ep.source_description, ep.name)
            if cat in relevant_categories:
                episodes.append(
                    MemoryEpisode(
                        uuid=ep.uuid,
                        name=ep.name,
                        content=ep.content,
                        source=self._map_episode_type(ep.source),
                        category=cat,
                        scope=self.scope,
                        scope_id=self.scope_id,
                        source_description=ep.source_description,
                        created_at=ep.created_at,
                        valid_at=ep.valid_at,
                        entities=ep.entity_edges,
                    )
                )

            if len(episodes) >= num_sessions:
                break

        return episodes

    async def _update_access_time(self, uuids: list[str]) -> None:
        """
        Update last_accessed_at timestamp for accessed memory items.

        Args:
            uuids: List of edge/episode UUIDs that were accessed
        """
        if not uuids:
            return

        driver = self._graphiti.driver
        now = utc_now().isoformat()

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

    def _get_category_keywords(self, category: MemoryCategory) -> list[str]:
        """Get keywords for category filtering in Cypher queries."""
        if category == MemoryCategory.CODING_STANDARD:
            return ["standard", "style", "convention", "best practice", "pattern"]
        elif category == MemoryCategory.TROUBLESHOOTING_GUIDE:
            return ["gotcha", "pitfall", "issue", "bug", "fix", "error", "warning", "troubleshoot"]
        elif category == MemoryCategory.SYSTEM_DESIGN:
            return ["architecture", "design", "structure", "decision", "system"]
        elif category == MemoryCategory.OPERATIONAL_CONTEXT:
            return ["environment", "deploy", "runtime", "config", "setup", "operational"]
        elif category == MemoryCategory.DOMAIN_KNOWLEDGE:
            return ["domain", "business", "requirement", "concept", "knowledge"]
        elif category == MemoryCategory.ACTIVE_STATE:
            return ["active", "current", "task", "session", "progress", "state"]
        return []

    async def _fetch_episodes_filtered(
        self,
        limit: int,
        reference_time: datetime,
        category: MemoryCategory | None = None,
    ) -> tuple[list[Any], bool]:
        """
        Fetch episodes with optional category filtering at database level.

        Returns:
            Tuple of (episodes_list, has_more)
        """
        # Build category filter WHERE clause
        category_filter = ""
        if category:
            # Filter by category prefix in source_description (from standardization)
            # Format: "category_name type:X tier:Y"
            category_filter = f"AND e.source_description STARTS WITH '{category.value} '"

        query = f"""
        MATCH (e:Episodic)
        WHERE e.group_id = $group_id
          AND e.valid_at <= datetime($reference_time)
          {category_filter}
        RETURN e.uuid AS uuid,
               e.name AS name,
               e.content AS content,
               e.source AS source,
               e.source_description AS source_description,
               e.created_at AS created_at,
               e.valid_at AS valid_at,
               e.entity_edges AS entity_edges
        ORDER BY e.valid_at DESC
        LIMIT $limit
        """

        records, _, _ = await self._graphiti.driver.execute_query(
            query,
            group_id=self._group_id,
            reference_time=reference_time.isoformat(),
            limit=limit + 1,
        )

        has_more = len(records) > limit
        records = records[:limit]

        # Convert Neo4j records to Episode-like objects
        from types import SimpleNamespace

        episodes = []
        for rec in records:
            # Convert Neo4j DateTime to Python datetime
            created_at = rec["created_at"]
            if hasattr(created_at, "to_native"):
                created_at = created_at.to_native()

            valid_at = rec["valid_at"]
            if hasattr(valid_at, "to_native"):
                valid_at = valid_at.to_native()

            ep = SimpleNamespace(
                uuid=rec["uuid"],
                name=rec["name"],
                content=rec["content"],
                source=rec["source"],
                source_description=rec["source_description"] or "",
                created_at=created_at,
                valid_at=valid_at,
                entity_edges=rec["entity_edges"] or [],
            )
            episodes.append(ep)

        return episodes, has_more

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

        # Use filtered query if category specified
        if category:
            episodes_raw, has_more = await self._fetch_episodes_filtered(
                limit, reference_time, category
            )
        else:
            # Use Graphiti's retrieve_episodes for unfiltered queries
            episodes_raw = await self._graphiti.retrieve_episodes(
                reference_time=reference_time,
                last_n=limit + 1,
                group_ids=[self._group_id],
            )
            # Reverse for newest-first
            episodes_raw = list(reversed(episodes_raw))
            has_more = len(episodes_raw) > limit
            episodes_raw = episodes_raw[:limit]

        # Convert to MemoryEpisode objects
        episodes: list[MemoryEpisode] = []
        for ep in episodes_raw:
            # Infer category from source_description or name
            cat = self._infer_category(ep.source_description, ep.name)

            episodes.append(
                MemoryEpisode(
                    uuid=ep.uuid,
                    name=ep.name,
                    content=ep.content,
                    source=self._map_episode_type(ep.source),
                    category=cat,
                    scope=self.scope,
                    scope_id=self.scope_id,
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
        """Infer category from source description or name using 6-category taxonomy."""
        # First check if category is explicitly stored in source_description (from standardization)
        # Format: "category_name type:X tier:Y"
        for cat in MemoryCategory:
            if source_desc.startswith(cat.value + " "):
                return cat

        # Fallback to keyword-based inference for legacy episodes
        combined = f"{source_desc} {name}".lower()

        # Coding standards - best practices, style guides, patterns to follow
        if any(
            kw in combined for kw in ["standard", "style", "convention", "best practice", "pattern"]
        ):
            return MemoryCategory.CODING_STANDARD

        # Troubleshooting - gotchas, pitfalls, known issues, fixes
        if any(
            kw in combined
            for kw in [
                "gotcha",
                "pitfall",
                "issue",
                "bug",
                "fix",
                "error",
                "warning",
                "troubleshoot",
            ]
        ):
            return MemoryCategory.TROUBLESHOOTING_GUIDE

        # System design - architecture, design decisions, structure
        if any(
            kw in combined for kw in ["architecture", "design", "structure", "decision", "system"]
        ):
            return MemoryCategory.SYSTEM_DESIGN

        # Operational context - environment, deployment, runtime, config
        if any(
            kw in combined
            for kw in ["environment", "deploy", "runtime", "config", "setup", "operational"]
        ):
            return MemoryCategory.OPERATIONAL_CONTEXT

        # Domain knowledge - business logic, domain concepts, requirements
        if any(
            kw in combined for kw in ["domain", "business", "requirement", "concept", "knowledge"]
        ):
            return MemoryCategory.DOMAIN_KNOWLEDGE

        # Active state - current task, in-progress work, session state
        if any(
            kw in combined for kw in ["active", "current", "task", "session", "progress", "state"]
        ):
            return MemoryCategory.ACTIVE_STATE

        # Default to domain knowledge for uncategorized content
        return MemoryCategory.DOMAIN_KNOWLEDGE

    def _map_episode_type(self, ep_type: EpisodeType) -> MemorySource:
        """Map Graphiti EpisodeType to our MemorySource."""
        # EpisodeType is message, json, text
        # Default to CHAT for message type
        if ep_type == EpisodeType.message:
            return MemorySource.CHAT
        else:
            return MemorySource.SYSTEM

    async def get_scope_stats(self) -> list[MemoryScopeCount]:
        """
        Get episode counts by scope.

        Returns list of scopes with their episode counts.
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
            # Parse group_ids to extract scopes
            scope_counts: dict[MemoryScope, int] = {}
            for record in records:
                group_id = record["group_id"] or "global"
                count = record["count"]

                # Parse scope from group_id (format: "global" or "scope-id")
                # build_group_id() uses dashes: "project-{id}"
                if group_id == "global":
                    scope = MemoryScope.GLOBAL
                elif group_id.startswith("project-"):
                    scope = MemoryScope.PROJECT
                else:
                    # Legacy or unknown group_ids default to GLOBAL
                    scope = MemoryScope.GLOBAL

                scope_counts[scope] = scope_counts.get(scope, 0) + count

            return [
                MemoryScopeCount(scope=scope, count=count)
                for scope, count in sorted(scope_counts.items(), key=lambda x: x[1], reverse=True)
            ]
        except Exception as e:
            logger.error("Failed to get scope stats: %s", e)
            return []

    async def get_stats(self) -> MemoryStats:
        """
        Get memory statistics for dashboard KPIs.

        Returns total count, breakdown by category and scope, and last updated time.
        """
        # Fetch all episodes (up to a reasonable limit for stats)
        episodes_raw = await self._graphiti.retrieve_episodes(
            reference_time=utc_now(),
            last_n=1000,  # Reasonable limit for stats
            group_ids=[self._group_id],
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

        # Get scope stats
        scope_stats = await self.get_scope_stats()

        return MemoryStats(
            total=len(episodes_raw),
            by_category=[
                MemoryCategoryCount(category=cat, count=count)
                for cat, count in sorted(category_counts.items(), key=lambda x: x[1], reverse=True)
            ],
            by_scope=scope_stats,
            last_updated=last_updated,
            scope=self.scope,
            scope_id=self.scope_id,
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
        now = utc_now()

        # First, check system activity - when was the last episode created?
        activity_query = """
        MATCH (e:Episodic {group_id: $group_id})
        RETURN max(e.created_at) AS last_activity
        """

        try:
            records, _, _ = await driver.execute_query(
                activity_query,
                group_id=self._group_id,
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
                group_id=self._group_id,
                cutoff=cutoff.isoformat(),
            )

            deleted = records[0]["deleted"] if records else 0
            logger.info(
                "Cleanup complete for group %s: %d stale memories deleted",
                self._group_id,
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
def get_memory_service(
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> MemoryService:
    """Get cached memory service instance for a scope."""
    return MemoryService(scope=scope, scope_id=scope_id)
