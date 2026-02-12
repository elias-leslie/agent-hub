"""Memory API schemas - Bulk operations."""

from pydantic import BaseModel, Field

from app.services.memory.types import InjectionTier

from .memory_schemas_episodes import EpisodeDetailResponse


class BulkDeleteRequest(BaseModel):
    """Request body for bulk episode deletion."""

    ids: list[str] = Field(..., min_length=1, description="Episode UUIDs to delete")


class BulkDeleteError(BaseModel):
    """Error detail for a single failed deletion."""

    id: str
    error: str


class BulkDeleteResponse(BaseModel):
    """Response body for bulk deletion."""

    deleted: int = Field(..., description="Number of successfully deleted episodes")
    failed: int = Field(..., description="Number of failed deletions")
    errors: list[BulkDeleteError] = Field(default_factory=list, description="Error details")


class CleanupResponse(BaseModel):
    """Response body for cleanup operation."""

    deleted: int
    skipped: bool
    reason: str | None = None


class BatchGetRequest(BaseModel):
    """Request body for batch episode retrieval."""

    uuids: list[str] = Field(
        ..., min_length=1, max_length=100, description="Episode UUIDs to retrieve"
    )


class BatchGetResponse(BaseModel):
    """Response body for batch episode retrieval."""

    episodes: dict[str, EpisodeDetailResponse] = Field(
        ..., description="Map of UUID to episode details"
    )
    found: int = Field(..., description="Number of episodes found")
    missing: list[str] = Field(default_factory=list, description="UUIDs not found")


class BatchUpdateItem(BaseModel):
    """Single item for batch episode update - supports any property."""

    uuid: str = Field(..., description="Episode UUID or 8-char prefix")
    injection_tier: InjectionTier | None = Field(None, description="New tier")
    summary: str | None = Field(None, description="Short action phrase for TOON (~20 chars)")
    trigger_task_types: list[str] | None = Field(
        None, description="Task types that trigger this episode"
    )
    pinned: bool | None = Field(None, description="Pin episode (always inject)")
    auto_inject: bool | None = Field(None, description="Auto-inject regardless of query")
    display_order: int | None = Field(
        None, description="Display order within tier (lower = earlier)"
    )


class BatchUpdateRequest(BaseModel):
    """Request body for batch episode updates."""

    updates: list[BatchUpdateItem] = Field(
        ..., min_length=1, max_length=500, description="List of episode updates"
    )


class BatchUpdateResult(BaseModel):
    """Result for a single episode update."""

    uuid: str
    success: bool
    error: str | None = None


class BatchUpdateResponse(BaseModel):
    """Response body for batch episode updates."""

    results: list[BatchUpdateResult]
    updated: int
    failed: int
    total: int


class OrphanedCleanupResponse(BaseModel):
    """Response body for combined orphaned cleanup (edges, entities, duplicates)."""

    edges_updated: int = Field(0, description="Edges with stale refs updated")
    edges_deleted: int = Field(0, description="Fully orphaned edges deleted")
    stale_refs_removed: int = Field(0, description="Total stale episode refs removed")
    entities_deleted: int = Field(0, description="Orphaned entities removed")
    duplicates_merged: int = Field(0, description="Duplicate entities consolidated")
    error: str | None = None
