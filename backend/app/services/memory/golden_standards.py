"""
Golden Standards service for high-confidence curated knowledge.

Golden standards are verified, critical knowledge that should always be
available in context when relevant. They are stored with confidence=100
and source=golden_standard to distinguish them from learned content.

Golden standards include:
- Critical coding constraints (async patterns, model selection)
- Security requirements (OAuth, no API keys for Claude)
- Architecture decisions (database patterns, error handling)
- Workflow mandates (commit protocol, quality gates)
"""

import logging
from datetime import UTC, datetime

from graphiti_core.nodes import EpisodeType

from .episode_formatter import InjectionTier, get_episode_formatter
from .graphiti_client import get_graphiti
from .service import (
    MemoryCategory,
    MemoryScope,
    MemorySearchResult,
    MemorySource,
    get_memory_service,
)

logger = logging.getLogger(__name__)

# Golden standard confidence level (100 = always trusted)
GOLDEN_CONFIDENCE = 100


async def store_golden_standard(
    content: str,
    category: MemoryCategory,
    *,
    title: str | None = None,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> str:
    """
    Store a golden standard in the knowledge graph.

    Golden standards are curated, high-confidence knowledge that should
    always be injected when relevant. They have:
    - confidence: 100 (always trusted)
    - tier: mandate (always-inject priority)
    - source: golden_standard

    Args:
        content: The golden standard content
        category: Memory category (CODING_STANDARD, SYSTEM_DESIGN, etc.)
        title: Optional title for the golden standard
        scope: Memory scope (GLOBAL, PROJECT, TASK)
        scope_id: Scope identifier for non-global scopes

    Returns:
        UUID of the created episode
    """
    formatter = get_episode_formatter()
    graphiti = get_graphiti()

    # Format the episode using the formatter
    episode = formatter.format_learning(
        content=content,
        category=category,
        title=title,
        tier=InjectionTier.MANDATE,
        is_golden=True,
        is_anti_pattern=False,
        confidence=GOLDEN_CONFIDENCE,
        scope=scope,
        scope_id=scope_id,
    )

    # Add episode to Graphiti
    result = await graphiti.add_episode(
        name=episode.name,
        episode_body=episode.episode_body,
        source=EpisodeType.text,
        source_description=episode.source_description,
        reference_time=episode.reference_time,
        group_id=episode.group_id,
    )

    logger.info(
        "Stored golden standard: %s (category=%s, scope=%s)",
        title or content[:50],
        category.value,
        scope.value,
    )

    return result.episode.uuid


async def get_golden_standards(
    query: str | None = None,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    max_results: int = 10,
) -> list[MemorySearchResult]:
    """
    Retrieve golden standards from the knowledge graph.

    If a query is provided, returns golden standards relevant to that query.
    If no query, returns the most frequently accessed golden standards.

    Args:
        query: Optional query to find relevant golden standards
        scope: Memory scope to query
        scope_id: Project or task ID for scoping
        max_results: Maximum results to return

    Returns:
        List of golden standard search results
    """
    service = get_memory_service(scope=scope, scope_id=scope_id)

    # Search query - use golden standard indicators
    search_query = query or "golden standard critical constraint mandate"
    search_query = f"golden standard critical: {search_query}"

    try:
        edges = await service._graphiti.search(
            query=search_query,
            group_ids=[service._group_id],
            num_results=max_results * 2,  # Fetch extra to filter
        )
    except Exception as e:
        logger.warning("Failed to search for golden standards: %s", e)
        return []

    results: list[MemorySearchResult] = []

    for edge in edges:
        # Golden standards have high relevance scores
        score = getattr(edge, "score", 0.0)
        if score < 0.5:
            continue

        fact = edge.fact or ""
        if not fact:
            continue

        results.append(
            MemorySearchResult(
                uuid=edge.uuid,
                content=fact,
                source=MemorySource.SYSTEM,
                relevance_score=score,
                created_at=edge.created_at,
                facts=[fact],
            )
        )

        if len(results) >= max_results:
            break

    return results


async def mark_as_golden_standard(
    episode_uuid: str,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> bool:
    """
    Mark an existing episode as a golden standard.

    Updates the episode's metadata to indicate it's a golden standard
    with confidence=100 and tier=mandate.

    Note: This requires updating the episode in Neo4j directly since
    Graphiti doesn't expose episode updates.

    Args:
        episode_uuid: UUID of the episode to mark as golden
        scope: Memory scope
        scope_id: Scope identifier

    Returns:
        True if successful, False otherwise
    """
    service = get_memory_service(scope=scope, scope_id=scope_id)
    driver = service._graphiti.driver

    # Update the episode's source_description to include golden standard markers
    now = datetime.now(UTC).isoformat()

    query = """
    MATCH (e:Episodic {uuid: $uuid})
    SET e.source_description = CASE
        WHEN e.source_description IS NULL THEN 'source:golden_standard confidence:100 tier:mandate'
        WHEN NOT e.source_description CONTAINS 'golden_standard' THEN
            e.source_description + ' source:golden_standard confidence:100 tier:mandate'
        ELSE e.source_description
    END,
    e.updated_at = datetime($now)
    RETURN e.uuid AS uuid
    """

    try:
        records, _, _ = await driver.execute_query(
            query,
            uuid=episode_uuid,
            now=now,
        )

        if records:
            logger.info("Marked episode %s as golden standard", episode_uuid)
            return True
        else:
            logger.warning("Episode %s not found", episode_uuid)
            return False

    except Exception as e:
        logger.error("Failed to mark episode as golden standard: %s", e)
        return False


async def list_golden_standards(
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """
    List all golden standards in the knowledge graph.

    Args:
        scope: Memory scope
        scope_id: Scope identifier
        limit: Maximum results

    Returns:
        List of golden standard episodes with metadata
    """
    service = get_memory_service(scope=scope, scope_id=scope_id)
    driver = service._graphiti.driver

    query = """
    MATCH (e:Episodic {group_id: $group_id})
    WHERE e.source_description CONTAINS 'golden_standard'
       OR e.source_description CONTAINS 'confidence:100'
    RETURN e.uuid AS uuid,
           e.name AS name,
           e.content AS content,
           e.source_description AS source_description,
           e.created_at AS created_at
    ORDER BY e.created_at DESC
    LIMIT $limit
    """

    try:
        records, _, _ = await driver.execute_query(
            query,
            group_id=service._group_id,
            limit=limit,
        )

        return [
            {
                "uuid": r["uuid"],
                "name": r["name"],
                "content": r["content"],
                "source_description": r["source_description"],
                "created_at": r["created_at"],
            }
            for r in records
        ]

    except Exception as e:
        logger.error("Failed to list golden standards: %s", e)
        return []


# Predefined golden standards for Agent Hub
AGENT_HUB_GOLDEN_STANDARDS = [
    {
        "content": "Claude uses OAuth, NOT API keys. User has Max subscription. NEVER suggest/check for ANTHROPIC_API_KEY.",
        "category": MemoryCategory.SYSTEM_DESIGN,
        "title": "Claude OAuth Requirement",
    },
    {
        "content": "All I/O is async. NEVER use sync methods. Use AsyncSession from get_db().",
        "category": MemoryCategory.CODING_STANDARD,
        "title": "Async Mandatory",
    },
    {
        "content": "Tasks must achieve both technical goals AND spirit of intent. No stubs, skeletons, or partial implementations.",
        "category": MemoryCategory.CODING_STANDARD,
        "title": "Task Completeness Mandate",
    },
    {
        "content": "Use model constants from app/constants.py. Never hardcode model strings.",
        "category": MemoryCategory.CODING_STANDARD,
        "title": "Model Selection Pattern",
    },
    {
        "content": """Plan-Verify-Execute Workflow: Before implementing features involving external dependencies, APIs, or unfamiliar patterns:
1. DISCOVERY: List dependencies involved (use check_dependency_version tool for version info)
2. VERIFICATION: WebSearch for current best practices and breaking changes
3. MULTI-PATTERN SURVEY: Find 3+ existing examples in codebase OR verify against official docs
4. COMPARE: Check codebase usage vs official documentation for discrepancies
Only proceed to implementation after verification passes. This prevents pattern-blindness bugs.""",
        "category": MemoryCategory.CODING_STANDARD,
        "title": "Plan-Verify-Execute Workflow",
    },
]


async def seed_golden_standards() -> int:
    """
    Seed the database with predefined golden standards.

    Returns the number of golden standards created.
    """
    created = 0

    for gs in AGENT_HUB_GOLDEN_STANDARDS:
        try:
            await store_golden_standard(
                content=gs["content"],
                category=gs["category"],
                title=gs.get("title"),
            )
            created += 1
        except Exception as e:
            logger.error("Failed to seed golden standard '%s': %s", gs.get("title"), e)

    logger.info("Seeded %d golden standards", created)
    return created
