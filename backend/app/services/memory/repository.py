"""Memory repository — CRUD + pgvector search on the unified memories table."""

from __future__ import annotations

import logging

from ._repo_analytics import AnalyticsRepository
from ._repo_crud import CrudRepository
from ._repo_helpers import TIER_MAP, TIER_REVERSE, to_dict
from ._repo_query import QueryRepository
from ._repo_search import SearchRepository
from ._repo_tier import TierRepository
from ._repo_tracking import TrackingRepository

logger = logging.getLogger(__name__)

__all__ = [
    "TIER_MAP",
    "TIER_REVERSE",
    "MemoryRepository",
    "get_memory_repository",
]


class MemoryRepository(
    CrudRepository,
    QueryRepository,
    SearchRepository,
    TierRepository,
    TrackingRepository,
    AnalyticsRepository,
):
    """Async repository for the unified memories table.

    All operations use SQLAlchemy async sessions against PostgreSQL + pgvector.

    Composed from focused sub-repositories:
    - CrudRepository: create, get, update, delete
    - QueryRepository: list, count, paginate, text search, UUID resolution
    - SearchRepository: semantic vector search
    - TierRepository: tier optimization and triggered references
    - TrackingRepository: usage counters and batch operations
    - AnalyticsRepository: stats and cleanup
    """

    @staticmethod
    def _to_dict(mem: object) -> dict:
        """Convert Memory ORM object to dict (backward compat)."""
        from app.models.memory_unified import Memory as _Memory
        assert isinstance(mem, _Memory)
        return to_dict(mem)


def get_memory_repository() -> MemoryRepository:
    """Get a MemoryRepository instance."""
    return MemoryRepository()
