"""
Graphiti knowledge graph service configuration.

Provides a configured Graphiti instance using Gemini for LLM and embeddings,
connected to local Neo4j.

Also provides helpers for extending Episodic nodes with custom properties
(injection_tier, usage stats) that Graphiti doesn't manage directly.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from neo4j import AsyncDriver

from graphiti_core import Graphiti
from graphiti_core.cross_encoder.gemini_reranker_client import GeminiRerankerClient
from graphiti_core.embedder.gemini import GeminiEmbedder, GeminiEmbedderConfig
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.gemini_client import GeminiClient

from app.config import settings
from app.constants import GEMINI_FLASH

logger = logging.getLogger(__name__)

# Gemini model for entity extraction (fast, cheap)
# Using gemini-2.5-flash-lite: same quality as gemini-3-flash, 5x faster (~2s vs ~10s)
GRAPHITI_LLM_MODEL = "gemini-2.5-flash-lite"

# Gemini model for reranking (fast, cheap)
GRAPHITI_RERANKER_MODEL = GEMINI_FLASH

# Gemini embedding model
# gemini-embedding-001 with output_dimensionality=768 for Neo4j index compatibility
# Migrated from text-embedding-004 (deprecated Jan 14, 2026)
# Using 768 dims via Matryoshka truncation - no index rebuild needed
GRAPHITI_EMBEDDING_MODEL = "gemini-embedding-001"
GRAPHITI_EMBEDDING_DIM = 768


def create_gemini_llm_client() -> GeminiClient:
    """Create Gemini LLM client for Graphiti entity extraction."""
    config = LLMConfig(
        api_key=settings.gemini_api_key,
        model=GRAPHITI_LLM_MODEL,
    )
    return GeminiClient(config=config)


def create_gemini_reranker() -> GeminiRerankerClient:
    """Create Gemini reranker for cross-encoder scoring."""
    config = LLMConfig(
        api_key=settings.gemini_api_key,
        model=GRAPHITI_RERANKER_MODEL,
    )
    return GeminiRerankerClient(config=config)


def create_gemini_embedder() -> GeminiEmbedder:
    """Create Gemini embedder for Graphiti semantic search."""
    config = GeminiEmbedderConfig(
        api_key=settings.gemini_api_key,
        embedding_model=GRAPHITI_EMBEDDING_MODEL,
        embedding_dim=GRAPHITI_EMBEDDING_DIM,
    )
    return GeminiEmbedder(config=config)


@lru_cache
def get_graphiti() -> Graphiti:
    """
    Get configured Graphiti instance.

    Returns a singleton Graphiti client connected to local Neo4j
    with Gemini LLM, embedder, and reranker.
    """
    logger.info("Initializing Graphiti with Neo4j at %s", settings.neo4j_uri)

    # Create providers
    llm_client = create_gemini_llm_client()
    embedder = create_gemini_embedder()
    cross_encoder = create_gemini_reranker()

    # Create Graphiti instance
    graphiti = Graphiti(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user or None,
        password=settings.neo4j_password or None,
        llm_client=llm_client,
        embedder=embedder,
        cross_encoder=cross_encoder,
    )

    logger.info("Graphiti initialized successfully")
    return graphiti


async def init_graphiti_schema() -> None:
    """Initialize Graphiti schema in Neo4j (run on startup)."""
    graphiti = get_graphiti()
    await graphiti.build_indices_and_constraints()
    logger.info("Graphiti schema initialized")


async def set_episode_injection_tier(
    episode_uuid: str,
    injection_tier: str,
    driver: AsyncDriver | None = None,
) -> bool:
    """
    Set injection_tier property on an Episodic node.

    This extends Graphiti's Episodic nodes with our tier-based injection system.
    Valid tiers: mandate, guardrail, reference, pending_review

    Args:
        episode_uuid: UUID of the episode to update
        injection_tier: Tier value (mandate/guardrail/reference/pending_review)
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        True if updated, False if episode not found
    """
    if driver is None:
        graphiti = get_graphiti()
        driver = cast("AsyncDriver", graphiti.driver)
        assert driver is not None, "Graphiti driver not initialized"

    query = """
    MATCH (e:Episodic {uuid: $uuid})
    SET e.injection_tier = $tier
    RETURN e.uuid AS uuid
    """

    try:
        records, _, _ = await driver.execute_query(
            query,
            uuid=episode_uuid,
            tier=injection_tier,
        )
        if records:
            logger.debug("Set injection_tier=%s for episode %s", injection_tier, episode_uuid[:8])
            return True
        logger.warning("Episode %s not found for tier update", episode_uuid[:8])
        return False
    except Exception as e:
        logger.error("Failed to set injection_tier for %s: %s", episode_uuid[:8], e)
        return False


async def init_episode_usage_properties(
    episode_uuid: str,
    driver: AsyncDriver | None = None,
) -> bool:
    """
    Initialize usage tracking properties on an Episodic node.

    Sets loaded_count and referenced_count to 0 for new episodes.
    These properties track how often the episode is loaded into context
    and how often it is actually cited/referenced by the LLM.

    Args:
        episode_uuid: UUID of the episode to initialize
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        True if updated, False if episode not found
    """
    if driver is None:
        graphiti = get_graphiti()
        driver = cast("AsyncDriver", graphiti.driver)
        assert driver is not None, "Graphiti driver not initialized"

    query = """
    MATCH (e:Episodic {uuid: $uuid})
    SET e.loaded_count = 0, e.referenced_count = 0
    RETURN e.uuid AS uuid
    """

    try:
        records, _, _ = await driver.execute_query(
            query,
            uuid=episode_uuid,
        )
        if records:
            logger.debug("Initialized usage properties for episode %s", episode_uuid[:8])
            return True
        logger.warning("Episode %s not found for usage init", episode_uuid[:8])
        return False
    except Exception as e:
        logger.error("Failed to init usage properties for %s: %s", episode_uuid[:8], e)
        return False


async def set_episode_pinned(
    episode_uuid: str,
    pinned: bool,
    driver: AsyncDriver | None = None,
) -> bool:
    """
    Set pinned property on an Episodic node.

    Pinned episodes are never automatically demoted by tier_optimizer,
    regardless of usage stats. Use for critical knowledge that must persist.

    Args:
        episode_uuid: UUID of the episode to update
        pinned: Whether to pin the episode
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        True if updated, False if episode not found
    """
    if driver is None:
        graphiti = get_graphiti()
        driver = cast("AsyncDriver", graphiti.driver)
        assert driver is not None, "Graphiti driver not initialized"

    query = """
    MATCH (e:Episodic {uuid: $uuid})
    SET e.pinned = $pinned
    RETURN e.uuid AS uuid
    """

    try:
        records, _, _ = await driver.execute_query(
            query,
            uuid=episode_uuid,
            pinned=pinned,
        )
        if records:
            logger.debug("Set pinned=%s for episode %s", pinned, episode_uuid[:8])
            return True
        logger.warning("Episode %s not found for pinned update", episode_uuid[:8])
        return False
    except Exception as e:
        logger.error("Failed to set pinned for %s: %s", episode_uuid[:8], e)
        return False


async def set_episode_auto_inject(
    episode_uuid: str,
    auto_inject: bool,
    driver: AsyncDriver | None = None,
) -> bool:
    """
    Set auto_inject property on an Episodic node.

    For reference-tier episodes, auto_inject=true makes them behave like
    mandates/guardrails - injected in every session regardless of query.
    Mandates and guardrails implicitly have auto_inject=true.

    Args:
        episode_uuid: UUID of the episode to update
        auto_inject: Whether to auto-inject the episode
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        True if updated, False if episode not found
    """
    if driver is None:
        graphiti = get_graphiti()
        driver = cast("AsyncDriver", graphiti.driver)
        assert driver is not None, "Graphiti driver not initialized"

    query = """
    MATCH (e:Episodic {uuid: $uuid})
    SET e.auto_inject = $auto_inject
    RETURN e.uuid AS uuid
    """

    try:
        records, _, _ = await driver.execute_query(
            query,
            uuid=episode_uuid,
            auto_inject=auto_inject,
        )
        if records:
            logger.debug("Set auto_inject=%s for episode %s", auto_inject, episode_uuid[:8])
            return True
        logger.warning("Episode %s not found for auto_inject update", episode_uuid[:8])
        return False
    except Exception as e:
        logger.error("Failed to set auto_inject for %s: %s", episode_uuid[:8], e)
        return False


async def set_episode_display_order(
    episode_uuid: str,
    display_order: int,
    driver: AsyncDriver | None = None,
) -> bool:
    """
    Set display_order property on an Episodic node.

    Controls injection ordering within the same tier. Lower values = earlier.
    Default is 50. Use 1-10 for high priority, 90-99 for low priority.

    Args:
        episode_uuid: UUID of the episode to update
        display_order: Order value (lower = earlier in injection)
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        True if updated, False if episode not found
    """
    if driver is None:
        graphiti = get_graphiti()
        driver = cast("AsyncDriver", graphiti.driver)
        assert driver is not None, "Graphiti driver not initialized"

    query = """
    MATCH (e:Episodic {uuid: $uuid})
    SET e.display_order = $display_order
    RETURN e.uuid AS uuid
    """

    try:
        records, _, _ = await driver.execute_query(
            query,
            uuid=episode_uuid,
            display_order=display_order,
        )
        if records:
            logger.debug("Set display_order=%s for episode %s", display_order, episode_uuid[:8])
            return True
        logger.warning("Episode %s not found for display_order update", episode_uuid[:8])
        return False
    except Exception as e:
        logger.error("Failed to set display_order for %s: %s", episode_uuid[:8], e)
        return False


async def copy_episode_stats(
    source_uuid: str,
    target_uuid: str,
    driver: AsyncDriver | None = None,
) -> bool:
    """
    Copy usage stats from one episode to another.

    Copies loaded_count, referenced_count, helpful_count, harmful_count,
    utility_score, pinned, auto_inject, and display_order from source to target.
    Used when editing episodes (delete + recreate) to preserve feedback data.

    Args:
        source_uuid: UUID of the episode to copy stats from
        target_uuid: UUID of the episode to copy stats to
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        True if copied, False if source or target not found
    """
    if driver is None:
        graphiti = get_graphiti()
        driver = cast("AsyncDriver", graphiti.driver)
        assert driver is not None, "Graphiti driver not initialized"

    query = """
    MATCH (source:Episodic {uuid: $source_uuid})
    MATCH (target:Episodic {uuid: $target_uuid})
    SET target.loaded_count = COALESCE(source.loaded_count, 0),
        target.referenced_count = COALESCE(source.referenced_count, 0),
        target.helpful_count = COALESCE(source.helpful_count, 0),
        target.harmful_count = COALESCE(source.harmful_count, 0),
        target.utility_score = source.utility_score,
        target.pinned = COALESCE(source.pinned, false),
        target.auto_inject = COALESCE(source.auto_inject, false),
        target.display_order = COALESCE(source.display_order, 50)
    RETURN target.uuid AS uuid
    """

    try:
        records, _, _ = await driver.execute_query(
            query,
            source_uuid=source_uuid,
            target_uuid=target_uuid,
        )
        if records:
            logger.debug("Copied stats from %s to %s", source_uuid[:8], target_uuid[:8])
            return True
        logger.warning(
            "Failed to copy stats: source %s or target %s not found",
            source_uuid[:8],
            target_uuid[:8],
        )
        return False
    except Exception as e:
        logger.error("Failed to copy stats from %s to %s: %s", source_uuid[:8], target_uuid[:8], e)
        return False


async def set_episode_trigger_task_types(
    episode_uuid: str,
    trigger_task_types: list[str],
    driver: AsyncDriver | None = None,
) -> bool:
    """
    Set trigger_task_types property on an Episodic node.

    Specifies which task_types should automatically inject this reference episode.
    For example, a database migration guide can have trigger_task_types=["database", "migration"].

    Args:
        episode_uuid: UUID of the episode to update
        trigger_task_types: List of task_type strings that trigger this episode
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        True if updated, False if episode not found
    """
    if driver is None:
        graphiti = get_graphiti()
        driver = cast("AsyncDriver", graphiti.driver)
        assert driver is not None, "Graphiti driver not initialized"

    query = """
    MATCH (e:Episodic {uuid: $uuid})
    SET e.trigger_task_types = $trigger_task_types
    RETURN e.uuid AS uuid
    """

    try:
        records, _, _ = await driver.execute_query(
            query,
            uuid=episode_uuid,
            trigger_task_types=trigger_task_types,
        )
        if records:
            logger.debug(
                "Set trigger_task_types=%s for episode %s",
                trigger_task_types,
                episode_uuid[:8],
            )
            return True
        logger.warning("Episode %s not found for trigger_task_types update", episode_uuid[:8])
        return False
    except Exception as e:
        logger.error("Failed to set trigger_task_types for %s: %s", episode_uuid[:8], e)
        return False


async def get_triggered_references(
    task_type: str,
    group_id: str = "global",
    driver: AsyncDriver | None = None,
) -> list[dict[str, Any]]:
    """
    Get reference episodes that are triggered by a specific task_type.

    Returns reference-tier episodes where the task_type is in trigger_task_types.
    Used for context-aware reference injection based on task type.

    Args:
        task_type: The task type to match against trigger_task_types
        group_id: Group ID to filter episodes (default: global)
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        List of episode dicts with uuid, content, name, trigger_task_types
    """
    if driver is None:
        graphiti = get_graphiti()
        driver = cast("AsyncDriver", graphiti.driver)
        assert driver is not None, "Graphiti driver not initialized"

    query = """
    MATCH (e:Episodic {group_id: $group_id})
    WHERE e.injection_tier = 'reference'
      AND e.trigger_task_types IS NOT NULL
      AND $task_type IN e.trigger_task_types
    RETURN e.uuid AS uuid,
           e.content AS content,
           e.name AS name,
           e.trigger_task_types AS trigger_task_types,
           COALESCE(e.display_order, 50) AS display_order
    ORDER BY COALESCE(e.display_order, 50) ASC, e.created_at DESC
    """

    try:
        records, _, _ = await driver.execute_query(
            query,
            task_type=task_type,
            group_id=group_id,
        )
        return [dict(r) for r in records]
    except Exception as e:
        logger.error("Failed to get triggered references for task_type=%s: %s", task_type, e)
        return []


async def get_episode_properties(
    episode_uuid: str,
    driver: AsyncDriver | None = None,
) -> dict[str, Any] | None:
    """
    Get all custom properties for an Episodic node.

    Returns injection_tier, pinned, auto_inject, display_order, trigger_task_types, and usage stats.

    Args:
        episode_uuid: UUID of the episode to query
        driver: Neo4j driver (uses Graphiti's driver if not provided)

    Returns:
        Dict with properties or None if episode not found
    """
    if driver is None:
        graphiti = get_graphiti()
        driver = cast("AsyncDriver", graphiti.driver)
        assert driver is not None, "Graphiti driver not initialized"

    query = """
    MATCH (e:Episodic {uuid: $uuid})
    RETURN e.uuid AS uuid,
           e.injection_tier AS injection_tier,
           COALESCE(e.pinned, false) AS pinned,
           COALESCE(e.auto_inject, false) AS auto_inject,
           COALESCE(e.display_order, 50) AS display_order,
           COALESCE(e.trigger_task_types, []) AS trigger_task_types,
           COALESCE(e.loaded_count, 0) AS loaded_count,
           COALESCE(e.referenced_count, 0) AS referenced_count,
           COALESCE(e.helpful_count, 0) AS helpful_count,
           COALESCE(e.harmful_count, 0) AS harmful_count
    """

    try:
        records, _, _ = await driver.execute_query(
            query,
            uuid=episode_uuid,
        )
        if records:
            return dict(records[0])
        return None
    except Exception as e:
        logger.error("Failed to get properties for %s: %s", episode_uuid[:8], e)
        return None
