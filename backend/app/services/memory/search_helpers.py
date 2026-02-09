"""
Common helpers for search operations.

Provides shared utilities for edge processing, score filtering, and category mapping.
"""

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from graphiti_core.edges import EntityEdge
else:
    EntityEdge = None

from .memory_models import MemoryCategory


def get_edge_score(edge: "EntityEdge") -> float:
    """Extract relevance score from edge."""
    return getattr(edge, "score", 1.0)


def filter_by_score(edges: list["EntityEdge"], min_score: float) -> list["EntityEdge"]:
    """Filter edges by minimum relevance score."""
    return [e for e in edges if get_edge_score(e) >= min_score]


def map_tier_to_category(tier: str | None) -> MemoryCategory:
    """Map injection tier to memory category."""
    if tier == "mandate":
        return MemoryCategory.MANDATE
    elif tier == "guardrail":
        return MemoryCategory.GUARDRAIL
    return MemoryCategory.REFERENCE


def extract_episode_candidates(
    edges: list["EntityEdge"], min_score: float
) -> list[tuple[str, float, str, datetime]]:
    """
    Extract episode candidates from edges.

    Returns list of (episode_uuid, score, fact, created_at) tuples.
    """
    candidates: list[tuple[str, float, str, datetime]] = []

    for edge in edges:
        score = get_edge_score(edge)
        if score < min_score:
            continue

        # EntityEdge.episodes[] contains episode UUIDs that reference this edge
        ep_uuids = getattr(edge, "episodes", [])
        if not ep_uuids:
            continue

        fact = edge.fact if hasattr(edge, "fact") and edge.fact else ""
        created = edge.created_at

        # Use first episode UUID (most relevant)
        candidates.append((ep_uuids[0], score, fact, created))

    return candidates


def extract_entity_names(edges: list["EntityEdge"], max_entities: int) -> list[str]:
    """Extract unique entity names from edge source/target nodes."""
    entities: list[str] = []
    seen_names: set[str] = set()

    for edge in edges[:max_entities]:
        source_name = getattr(edge, "source_node_name", None)
        target_name = getattr(edge, "target_node_name", None)

        for name in [source_name, target_name]:
            if name and name not in seen_names:
                entities.append(name)
                seen_names.add(name)

    return entities


def extract_facts(edges: list["EntityEdge"], max_facts: int) -> list[str]:
    """Extract facts from edges."""
    facts: list[str] = []

    for edge in edges[:max_facts]:
        if hasattr(edge, "fact") and edge.fact:
            facts.append(edge.fact)

    return facts
