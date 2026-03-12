"""
High-level memory service for Agent Hub.

Wraps MemoryRepository (PostgreSQL + pgvector) with application-specific
methods for storing and retrieving conversational memory, voice transcripts,
and user preferences.
"""

import logging
from functools import lru_cache
from typing import Any

from . import service_stats as stats_ops
from .list_operations import list_episodes_paginated
from .memory_models import (
    MemoryCategory,
    MemoryCategoryCount,
    MemoryContext,
    MemoryEpisode,
    MemoryListResult,
    MemoryScope,
    MemoryScopeCount,
    MemorySearchResult,
    MemorySource,
    MemoryStats,
)
from .memory_utils import build_group_id, resolve_uuid_prefix
from .repository import get_memory_repository
from .service_mixins import _ServiceCrudMixin, _ServiceSearchMixin

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = [
    "MemoryCategory",
    "MemoryCategoryCount",
    "MemoryContext",
    "MemoryEpisode",
    "MemoryListResult",
    "MemoryScope",
    "MemoryScopeCount",
    "MemorySearchResult",
    "MemoryService",
    "MemorySource",
    "MemoryStats",
    "build_group_id",
    "get_memory_service",
    "resolve_uuid_prefix",
]


class MemoryService(_ServiceSearchMixin, _ServiceCrudMixin):
    """
    High-level memory service for storing and retrieving conversational context.

    Uses PostgreSQL + pgvector via MemoryRepository for semantic memory with
    episodic recall.
    """

    def __init__(
        self,
        scope: MemoryScope = MemoryScope.GLOBAL,
        scope_id: str | None = None,
        session_id: str | None = None,
    ):
        from .state import MemoryState

        self.scope = scope
        self.scope_id = scope_id
        self._group_id = build_group_id(scope, scope_id)
        self._repo = get_memory_repository()
        self._state: MemoryState | None = None
        if session_id:
            self._state = MemoryState.load(session_id)
            if not self._state:
                self._state = MemoryState(
                    session_id=session_id, scope=scope, scope_id=scope_id
                )
                self._state.save()

    async def health_check(self) -> dict[str, Any]:
        """Check memory system health."""
        try:
            # Verify database connectivity by running a lightweight query
            stats = await self._repo.get_stats(scope=self.scope.value)
            return {
                "status": "healthy",
                "database": "connected",
                "scope": self.scope.value,
                "scope_id": self.scope_id,
                "total_memories": stats.get("total", 0),
            }
        except Exception as e:
            logger.error("Memory health check failed: %s", e)
            return {
                "status": "unhealthy",
                "database": "disconnected",
                "error": str(e),
            }

    async def list_episodes(
        self,
        limit: int = 50,
        cursor: str | None = None,
        category: MemoryCategory | None = None,
        all_groups: bool = False,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
    ) -> MemoryListResult:
        """List episodes with cursor-based pagination."""
        group_id = None if all_groups else self._group_id
        return await list_episodes_paginated(
            group_id, self.scope, self.scope_id, limit, cursor, category, sort_by, sort_order
        )

    async def get_scope_stats(self) -> list[MemoryScopeCount]:
        """Get episode counts by scope."""
        return await stats_ops.get_all_scope_stats()

    async def get_stats(self, all_groups: bool = False) -> MemoryStats:
        """Get memory statistics for dashboard KPIs."""
        group_id = None if all_groups else self._group_id
        return await stats_ops.get_memory_stats(
            group_id, self.scope, self.scope_id
        )

    async def close(self) -> None:
        """Close connections (no-op for PostgreSQL — connection pool managed by SQLAlchemy)."""
        pass


@lru_cache
def get_memory_service(
    scope: MemoryScope = MemoryScope.GLOBAL, scope_id: str | None = None
) -> MemoryService:
    """Get cached memory service instance for a scope."""
    return MemoryService(scope=scope, scope_id=scope_id)
