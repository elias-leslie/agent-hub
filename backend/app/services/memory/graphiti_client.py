"""
Graphiti knowledge graph service configuration.

Provides a configured Graphiti instance using Gemini for LLM and embeddings,
connected to local Neo4j.

Auth strategy:
- LLM + reranker → CloudCode OAuth (zero-cost, per-user quota)
- Embeddings → API key (CloudCode has no embed endpoint)
- Falls back to API key for everything if OAuth unavailable.

Also provides helpers for extending Episodic nodes with custom properties
(injection_tier, usage stats) that Graphiti doesn't manage directly.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from graphiti_core import Graphiti
from graphiti_core.cross_encoder.gemini_reranker_client import GeminiRerankerClient
from graphiti_core.embedder.gemini import GeminiEmbedder, GeminiEmbedderConfig
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.gemini_client import GeminiClient

from app.config import settings
from app.constants import GEMINI_2_5_FLASH_LITE, GEMINI_FLASH

logger = logging.getLogger(__name__)

# Gemini model for entity extraction (fast, cheap)
# Using gemini-2.5-flash-lite: same quality as gemini-3-flash, 5x faster (~2s vs ~10s)
GRAPHITI_LLM_MODEL = GEMINI_2_5_FLASH_LITE

# Gemini model for reranking (fast, cheap)
GRAPHITI_RERANKER_MODEL = GEMINI_FLASH

# Gemini embedding model
# gemini-embedding-001 with output_dimensionality=768 for Neo4j index compatibility
# Migrated from text-embedding-004 (deprecated Jan 14, 2026)
# Using 768 dims via Matryoshka truncation - no index rebuild needed
GRAPHITI_EMBEDDING_MODEL = "gemini-embedding-001"
GRAPHITI_EMBEDDING_DIM = 768


def _resolve_gemini_api_key() -> str:
    """Resolve Gemini API key: DB credential → env var fallback."""
    from app.services.credential_manager import get_credential_manager

    cm = get_credential_manager()
    if cm.is_initialized:
        key = cm.get_api_key("gemini")
        if key:
            return key
    return settings.gemini_api_key


def _resolve_cloudcode_proxy() -> Any | None:
    """Build a CloudCodeGenaiProxy if OAuth credentials + project are available.

    Returns the proxy (duck-typed genai.Client) or None to fall back to API key.
    """
    try:
        from app.adapters.gemini import get_gemini_vertex_project
        from app.services.credential_manager import get_credential_manager

        cm = get_credential_manager()
        if not cm.is_initialized:
            return None

        token_json = cm.get("gemini", "oauth_token")
        if not token_json:
            return None

        data = json.loads(token_json)
        access_token = data.get("access_token")
        if not access_token:
            return None

        refresh_token = cm.get("gemini", "refresh_token")
        project_id = data.get("project_id") or get_gemini_vertex_project()
        if not project_id:
            return None

        from app.adapters.gemini_cloudcode import CloudCodeClient

        from .cloudcode_genai_proxy import CloudCodeGenaiProxy

        cc_client = CloudCodeClient(
            access_token=access_token,
            refresh_token=refresh_token,
            project_id=project_id,
            expires_at=data.get("expires_at"),
        )
        logger.info(
            "Graphiti using CloudCode OAuth (project=%s) for LLM + reranker",
            project_id,
        )
        return CloudCodeGenaiProxy(cc_client)
    except Exception:
        logger.debug("CloudCode proxy unavailable, falling back to API key", exc_info=True)
        return None


def create_gemini_llm_client() -> GeminiClient:
    """Create Gemini LLM client for Graphiti entity extraction.

    Prefers CloudCode OAuth; falls back to API key.
    """
    proxy = _resolve_cloudcode_proxy()
    config = LLMConfig(
        api_key=_resolve_gemini_api_key(),
        model=GRAPHITI_LLM_MODEL,
    )
    if proxy:
        return GeminiClient(config=config, client=proxy)
    return GeminiClient(config=config)


def create_gemini_reranker() -> GeminiRerankerClient:
    """Create Gemini reranker for cross-encoder scoring.

    Prefers CloudCode OAuth; falls back to API key.
    """
    proxy = _resolve_cloudcode_proxy()
    config = LLMConfig(
        api_key=_resolve_gemini_api_key(),
        model=GRAPHITI_RERANKER_MODEL,
    )
    if proxy:
        return GeminiRerankerClient(config=config, client=proxy)
    return GeminiRerankerClient(config=config)


def create_gemini_embedder() -> GeminiEmbedder:
    """Create Gemini embedder for Graphiti semantic search.

    Always uses API key (CloudCode has no embed endpoint).
    """
    config = GeminiEmbedderConfig(
        api_key=_resolve_gemini_api_key(),
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


# Re-export episode property management functions for backward compatibility
from app.services.memory.episode_properties import (  # noqa: E402
    batch_set_episode_injection_tier,
    batch_update_episode_properties,
    copy_episode_stats,
    get_episode_properties,
    get_phase_triggered_references,
    get_triggered_references,
    init_episode_usage_properties,
    set_episode_auto_inject,
    set_episode_display_order,
    set_episode_injection_tier,
    set_episode_pinned,
    set_episode_summary,
    set_episode_trigger_phases,
    set_episode_trigger_task_types,
)

__all__ = [
    "GRAPHITI_LLM_MODEL",
    "batch_set_episode_injection_tier",
    "batch_update_episode_properties",
    "copy_episode_stats",
    "create_gemini_embedder",
    "create_gemini_llm_client",
    "create_gemini_reranker",
    "get_episode_properties",
    "get_graphiti",
    "get_phase_triggered_references",
    "get_triggered_references",
    "init_episode_usage_properties",
    "init_graphiti_schema",
    "set_episode_auto_inject",
    "set_episode_display_order",
    "set_episode_injection_tier",
    "set_episode_pinned",
    "set_episode_summary",
    "set_episode_trigger_phases",
    "set_episode_trigger_task_types",
]
