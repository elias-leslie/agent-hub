"""Entity browser API endpoints for memory entities."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


@router.get("/entities")
async def list_entities(
    group_id: Annotated[str, Query(description="Group ID to filter entities")],
    search: Annotated[str | None, Query(description="Case-insensitive name search")] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="Max entities")] = 200,
    offset: Annotated[int, Query(ge=0, description="Pagination offset")] = 0,
) -> Any:
    from app.services.memory.entity_service import list_entities as svc_list

    try:
        return await svc_list(None, group_id, search=search, limit=limit, offset=offset)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list entities: {e}") from e


@router.get("/entities/health")
async def get_entity_health(
    group_id: Annotated[str, Query(description="Group ID")],
) -> Any:
    from app.services.memory.entity_service import get_entity_health as svc_health

    try:
        return await svc_health(None, group_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get entity health: {e}") from e


@router.get("/entities/{entity_name}/episodes")
async def get_entity_episodes(
    entity_name: str,
    group_id: Annotated[str, Query(description="Group ID")],
    limit: Annotated[int, Query(ge=1, le=100, description="Max episodes")] = 50,
) -> Any:
    from app.services.memory.entity_service import get_entity_episodes as svc_episodes

    try:
        return await svc_episodes(None, entity_name, group_id, limit=limit)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get entity episodes: {e}"
        ) from e
