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
from typing import TYPE_CHECKING, cast

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
