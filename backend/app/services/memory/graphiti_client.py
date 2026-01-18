"""
Graphiti knowledge graph service configuration.

Provides a configured Graphiti instance using Gemini for LLM and embeddings,
connected to local Neo4j.
"""

import logging
from functools import lru_cache

from graphiti_core import Graphiti
from graphiti_core.cross_encoder.gemini_reranker_client import GeminiRerankerClient
from graphiti_core.embedder.gemini import GeminiEmbedder, GeminiEmbedderConfig
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.gemini_client import GeminiClient

from app.config import settings
from app.constants import GEMINI_FLASH

logger = logging.getLogger(__name__)

# Gemini model for entity extraction (fast, cheap)
GRAPHITI_LLM_MODEL = GEMINI_FLASH

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
