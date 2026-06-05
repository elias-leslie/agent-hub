"""Memory API - Episode Tag Management Endpoints."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()

RenderMode = Literal["full", "compact", "summary"]


class TagsResponse(BaseModel):
    uuid: str
    tags: list[str]


class SetTagsRequest(BaseModel):
    tags: list[str] = Field(default_factory=list)


class BulkTagRequest(BaseModel):
    uuids: list[str] = Field(min_length=1, max_length=100)
    add_tags: list[str] = Field(default_factory=list)
    remove_tags: list[str] = Field(default_factory=list)


class BulkTagResponse(BaseModel):
    updated: int
    failed: int


class DistinctTagsResponse(BaseModel):
    tags: list[str]
    count: int


@router.get("/episodes/{uuid}/tags", response_model=TagsResponse)
async def get_episode_tags_endpoint(uuid: str) -> TagsResponse:
    """Get tags for an episode."""
    from app.services.memory.episode_property_queries import get_episode_tags

    tags = await get_episode_tags(uuid)
    return TagsResponse(uuid=uuid, tags=tags)


@router.put("/episodes/{uuid}/tags", response_model=TagsResponse)
async def set_episode_tags_endpoint(uuid: str, body: SetTagsRequest) -> TagsResponse:
    """Set (replace) tags on an episode."""
    from app.services.memory.episode_property_setters import set_episode_tags

    updated = await set_episode_tags(uuid, body.tags)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Episode {uuid} not found")
    return TagsResponse(uuid=uuid, tags=body.tags)


@router.post("/episodes/bulk-tag", response_model=BulkTagResponse)
async def bulk_tag_episodes_endpoint(body: BulkTagRequest) -> BulkTagResponse:
    """Bulk add/remove tags on multiple episodes."""
    from app.services.memory.episode_property_queries import get_episode_tags
    from app.services.memory.episode_property_setters import set_episode_tags

    if not body.add_tags and not body.remove_tags:
        raise HTTPException(status_code=400, detail="Must provide add_tags or remove_tags")

    updated = 0
    failed = 0
    for uuid in body.uuids:
        try:
            current = await get_episode_tags(uuid)
            new_tags = list(set(current) | set(body.add_tags) - set(body.remove_tags))
            result = await set_episode_tags(uuid, sorted(new_tags))
            if result:
                updated += 1
            else:
                failed += 1
        except Exception:
            logger.debug("Failed to update tags for episode %s", uuid, exc_info=True)
            failed += 1

    return BulkTagResponse(updated=updated, failed=failed)


@router.get("/tags", response_model=DistinctTagsResponse)
async def get_distinct_tags_endpoint() -> DistinctTagsResponse:
    """List all distinct tags across all episodes (for autocomplete)."""
    from app.services.memory.episode_property_queries import get_all_distinct_tags

    tags = await get_all_distinct_tags()
    return DistinctTagsResponse(tags=tags, count=len(tags))


class BulkRenderModeRequest(BaseModel):
    uuids: list[str] = Field(min_length=1, max_length=100)
    render_mode: RenderMode | None = Field(
        None,
        description=(
            "New render mode for the listed episodes. None / null clears the "
            "override and reverts to auto/profile-driven tier selection."
        ),
    )


class BulkRenderModeResponse(BaseModel):
    updated: int
    failed: int


@router.post("/episodes/bulk-render-mode", response_model=BulkRenderModeResponse)
async def bulk_render_mode_endpoint(body: BulkRenderModeRequest) -> BulkRenderModeResponse:
    """Bulk-set the per-memory render_mode preference on a list of episodes."""
    from app.services.memory.episode_property_setters import set_episode_render_mode

    if not body.uuids:
        raise HTTPException(status_code=400, detail="uuids must be non-empty")

    updated = 0
    failed = 0
    for uuid in body.uuids:
        try:
            ok = await set_episode_render_mode(uuid, body.render_mode)
            if ok:
                updated += 1
            else:
                failed += 1
        except Exception:
            logger.debug("Failed to set render_mode for episode %s", uuid, exc_info=True)
            failed += 1

    return BulkRenderModeResponse(updated=updated, failed=failed)
