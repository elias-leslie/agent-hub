"""
Search and retrieval operations for memory service.

Handles semantic search, context retrieval, and pattern/gotcha queries.
"""

import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from graphiti_core import Graphiti
else:
    # Runtime - get from graphiti_client
    Graphiti = None

from .memory_models import (
    MemoryCategory,
    MemoryContext,
    MemoryEpisode,
    MemoryScope,
    MemorySearchResult,
    MemorySource,
)
from .memory_queries import update_access_time, update_episode_access_time, validate_episodes
from .memory_utils import map_episode_type

logger = logging.getLogger(__name__)


async def search_memory(
    graphiti: "Graphiti",
    group_id: str,
    scope: MemoryScope,
    query: str,
    limit: int = 10,
    min_score: float = 0.0,
) -> list[MemorySearchResult]:
    """
    Search memory for relevant episodes and facts.

    Returns episode UUIDs (not edge UUIDs) for compatibility with get_episode().
    Validates episode existence and deduplicates by episode UUID.

    Args:
        graphiti: Graphiti client instance
        group_id: Group ID for scoping
        scope: Memory scope
        query: Search query
        limit: Maximum results to return
        min_score: Minimum relevance score (0-1)

    Returns:
        List of relevant memory results with valid episode UUIDs
    """
    # Graphiti.search() returns list[EntityEdge] directly
    edges = await graphiti.search(
        query=query,
        group_ids=[group_id],
        num_results=limit * 3,  # Fetch more to account for dedup/filtering
    )

    # Collect episode UUIDs from edges (edges have episodes[] backref)
    episode_candidates: list[
        tuple[str, float, str, datetime]
    ] = []  # (ep_uuid, score, fact, created)
    for edge in edges:
        score = getattr(edge, "score", 1.0)
        if score < min_score:
            continue

        # EntityEdge.episodes[] contains episode UUIDs that reference this edge
        ep_uuids = getattr(edge, "episodes", [])
        if not ep_uuids:
            continue

        fact = edge.fact if hasattr(edge, "fact") and edge.fact else ""
        created = edge.created_at

        # Use first episode UUID (most relevant)
        episode_candidates.append((ep_uuids[0], score, fact, created))

    # Validate episode existence and deduplicate
    valid_episodes = await validate_episodes(graphiti.driver, [c[0] for c in episode_candidates])

    search_results: list[MemorySearchResult] = []
    seen_uuids: set[str] = set()
    valid_episode_uuids: list[str] = []

    for ep_uuid, score, fact, created in episode_candidates:
        if ep_uuid not in valid_episodes:
            continue
        if ep_uuid in seen_uuids:
            continue

        seen_uuids.add(ep_uuid)
        search_results.append(
            MemorySearchResult(
                uuid=ep_uuid,
                content=fact,
                source=MemorySource.CHAT,
                relevance_score=score,
                created_at=created,
                facts=[fact] if fact else [],
                scope=scope,
            )
        )
        valid_episode_uuids.append(ep_uuid)

        if len(search_results) >= limit:
            break

    # Update access timestamps for returned episodes
    if valid_episode_uuids:
        await update_episode_access_time(graphiti.driver, valid_episode_uuids)

    return search_results


async def get_context_for_query(
    graphiti: "Graphiti",
    group_id: str,
    scope: MemoryScope,
    query: str,
    max_facts: int = 10,
    max_entities: int = 5,
) -> MemoryContext:
    """
    Get relevant context for a query to inject into LLM prompts.

    Args:
        graphiti: Graphiti client instance
        group_id: Group ID for scoping
        scope: Memory scope
        query: The user query to find context for
        max_facts: Maximum facts to include
        max_entities: Maximum entities to include

    Returns:
        MemoryContext with relevant facts, entities, and episodes
    """
    # Graphiti.search() returns list[EntityEdge] directly
    edges = await graphiti.search(
        query=query,
        group_ids=[group_id],
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
                scope=scope,
            )
        )

    # Update access timestamps for accessed edges
    if edges:
        await update_access_time(graphiti.driver, [e.uuid for e in edges])

    return MemoryContext(
        query=query,
        relevant_facts=facts,
        relevant_entities=entities,
        episodes=episodes,
    )


async def get_patterns_and_gotchas(
    graphiti: "Graphiti",
    group_id: str,
    scope: MemoryScope,
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
        graphiti: Graphiti client instance
        group_id: Group ID for scoping
        scope: Memory scope
        query: The query to find patterns and gotchas for
        num_results: Maximum results per category
        min_score: Minimum relevance score (0-1)

    Returns:
        Tuple of (patterns, gotchas) lists
    """
    # Search for coding standards/patterns
    pattern_query = f"coding standard pattern: {query}"
    pattern_edges = await graphiti.search(
        query=pattern_query,
        group_ids=[group_id],
        num_results=num_results * 2,  # Fetch more to filter
    )

    # Search for troubleshooting/gotchas
    gotcha_query = f"troubleshooting gotcha pitfall: {query}"
    gotcha_edges = await graphiti.search(
        query=gotcha_query,
        group_ids=[group_id],
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

        # Use injection_tier directly; default to REFERENCE for Graphiti API results
        tier = getattr(edge, "injection_tier", None)
        if tier == "mandate":
            category = MemoryCategory.MANDATE
        elif tier == "guardrail":
            category = MemoryCategory.GUARDRAIL
        else:
            category = MemoryCategory.REFERENCE

        if category == MemoryCategory.REFERENCE:
            patterns.append(
                MemorySearchResult(
                    uuid=edge.uuid,
                    content=edge.fact or "",
                    source=MemorySource.CHAT,
                    relevance_score=score,
                    created_at=edge.created_at,
                    facts=[edge.fact] if edge.fact else [],
                    scope=scope,
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

        # Use injection_tier directly; default to REFERENCE for Graphiti API results
        tier = getattr(edge, "injection_tier", None)
        if tier == "mandate":
            category = MemoryCategory.MANDATE
        elif tier == "guardrail":
            category = MemoryCategory.GUARDRAIL
        else:
            category = MemoryCategory.REFERENCE

        if category == MemoryCategory.GUARDRAIL:
            gotchas.append(
                MemorySearchResult(
                    uuid=edge.uuid,
                    content=edge.fact or "",
                    source=MemorySource.CHAT,
                    relevance_score=score,
                    created_at=edge.created_at,
                    facts=[edge.fact] if edge.fact else [],
                    scope=scope,
                    category=category,
                )
            )
            all_uuids.append(edge.uuid)

        if len(gotchas) >= num_results:
            break

    # Update access timestamps
    if all_uuids:
        await update_access_time(graphiti.driver, all_uuids)

    return patterns, gotchas


async def get_session_history(
    graphiti: "Graphiti",
    group_id: str,
    scope: MemoryScope,
    scope_id: str | None,
    num_sessions: int = 5,
) -> list[MemoryEpisode]:
    """
    Get recent session recommendations and insights.

    Retrieves episodes from recent sessions that contain insights,
    recommendations, or learnings that may be relevant for the current session.

    Args:
        graphiti: Graphiti client instance
        group_id: Group ID for scoping
        scope: Memory scope
        scope_id: Scope identifier
        num_sessions: Maximum number of recent sessions to retrieve from

    Returns:
        List of relevant session episodes
    """
    from graphiti_core.utils.datetime_utils import utc_now

    episodes_raw = await graphiti.retrieve_episodes(
        reference_time=utc_now(),
        last_n=num_sessions * 10,  # Fetch more to filter for relevant types
        group_ids=[group_id],
    )

    # Filter for session-relevant categories (all tiers are relevant)
    relevant_categories = {
        MemoryCategory.REFERENCE,
        MemoryCategory.GUARDRAIL,
    }

    episodes: list[MemoryEpisode] = []
    for ep in episodes_raw:
        # Use injection_tier directly; default to REFERENCE for Graphiti API results
        tier = getattr(ep, "injection_tier", None)
        if tier == "mandate":
            cat = MemoryCategory.MANDATE
        elif tier == "guardrail":
            cat = MemoryCategory.GUARDRAIL
        else:
            cat = MemoryCategory.REFERENCE

        if cat in relevant_categories:
            episodes.append(
                MemoryEpisode(
                    uuid=ep.uuid,
                    name=ep.name,
                    content=ep.content,
                    source=map_episode_type(ep.source),
                    category=cat,
                    scope=scope,
                    scope_id=scope_id,
                    source_description=ep.source_description,
                    created_at=ep.created_at,
                    valid_at=ep.valid_at,
                    entities=ep.entity_edges,
                )
            )

        if len(episodes) >= num_sessions:
            break

    return episodes
