"""Memory API - Shared Dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException

from app.services.memory import MemoryService, get_memory_service
from app.services.memory.memory_utils import resolve_uuid_prefix
from app.services.memory.service import MemoryScope


def get_scope_params(
    x_memory_scope: Annotated[str | None, Header()] = None,
    x_scope_id: Annotated[str | None, Header()] = None,
) -> tuple[MemoryScope, str | None]:
    """Get scope parameters from headers or use defaults."""
    scope = MemoryScope.GLOBAL
    if x_memory_scope:
        scope_value = x_memory_scope.lower()
        valid_scopes = [s.value for s in MemoryScope]
        if scope_value in valid_scopes:
            scope = MemoryScope(scope_value)
    return scope, x_scope_id


def get_memory_svc(
    scope_params: Annotated[tuple[MemoryScope, str | None], Depends(get_scope_params)],
) -> MemoryService:
    """Get memory service instance for the scope."""
    scope, scope_id = scope_params
    return get_memory_service(scope, scope_id)


async def resolve_episode_uuid(episode_id: str) -> str:
    """Resolve an episode UUID prefix to full UUID. FastAPI dependency.

    Searches across all groups so project-scoped episodes are accessible.
    """
    try:
        return await resolve_uuid_prefix(episode_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
