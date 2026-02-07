"""Memory API - Episode Tag Management Endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field

from fastapi import APIRouter, HTTPException

router = APIRouter()


class TagsResponse(BaseModel):
    uuid: str
    tags: list[str]


class SetTagsRequest(BaseModel):
    tags: list[str] = Field(default_factory=list)


class BulkTagRequest(BaseModel):
    uuids: list[str]
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
            failed += 1

    return BulkTagResponse(updated=updated, failed=failed)


@router.get("/tags", response_model=DistinctTagsResponse)
async def get_distinct_tags_endpoint() -> DistinctTagsResponse:
    """List all distinct tags across all episodes (for autocomplete)."""
    from app.services.memory.episode_property_queries import get_all_distinct_tags

    tags = await get_all_distinct_tags()
    return DistinctTagsResponse(tags=tags, count=len(tags))
