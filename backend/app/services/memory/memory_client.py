"""
Unified memory client.

Central entry point for all memory operations. Uses PostgreSQL + pgvector.
"""

from __future__ import annotations

import logging

from app.constants.models import GEMINI_EMBEDDING
from app.services.memory.embedder import EmbedderService, get_embedder
from app.services.memory.repository import MemoryRepository, get_memory_repository

logger = logging.getLogger(__name__)

# Re-export core components
__all__ = [
    "EmbedderService",
    "MemoryRepository",
    "get_embedder",
    "get_memory_repository",
    "init_memory_schema",
]

# Embedding configuration
EMBEDDING_MODEL = GEMINI_EMBEDDING
EMBEDDING_DIM = 768


async def init_memory_schema() -> None:
    """Initialize memory schema — no-op for PostgreSQL (handled by Alembic migrations)."""
    logger.info("Memory schema initialized (PostgreSQL + pgvector via Alembic)")
