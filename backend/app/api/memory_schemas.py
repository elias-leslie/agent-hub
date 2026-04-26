"""Memory API schemas - Request/response models.

This module re-exports all schemas from focused submodules for backward compatibility.
All imports remain available from app.api.memory_schemas.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

from app.services.memory.service import MemorySearchResult

# Re-export bulk operation schemas
from .memory_schemas_bulk import (
    BatchGetRequest,
    BatchGetResponse,
    BatchUpdateItem,
    BatchUpdateRequest,
    BatchUpdateResponse,
    BatchUpdateResult,
    BulkDeleteError,
    BulkDeleteRequest,
    BulkDeleteResponse,
    CleanupResponse,
)

# Re-export episode CRUD schemas
from .memory_schemas_episodes import (
    AddEpisodeRequest,
    AddEpisodeResponse,
    DeleteEpisodeResponse,
    EpisodeDetailResponse,
    MemoryRestoreRequest,
    MemoryRevisionListResponse,
    MemoryRevisionResponse,
    UpdateEpisodePropertiesRequest,
    UpdateEpisodePropertiesResponse,
    UpdateEpisodeRequest,
    UpdateEpisodeResponse,
)

# Re-export settings schemas
from .memory_schemas_settings import (
    BudgetUsageResponse,
    SettingsResponse,
    SettingsUpdateRequest,
)

__all__ = [
    "AddEpisodeRequest",
    "AddEpisodeResponse",
    "BatchGetRequest",
    "BatchGetResponse",
    "BatchUpdateItem",
    "BatchUpdateRequest",
    "BatchUpdateResponse",
    "BatchUpdateResult",
    "BudgetUsageResponse",
    "BulkDeleteError",
    "BulkDeleteRequest",
    "BulkDeleteResponse",
    "CleanupResponse",
    "DeleteEpisodeResponse",
    "EpisodeDetailResponse",
    "HealthResponse",
    "MemoryRestoreRequest",
    "MemoryReviewRunRequest",
    "MemoryReviewRunResponse",
    "MemoryRevisionListResponse",
    "MemoryRevisionResponse",
    "PhaseTriggeredReferenceItem",
    "PhaseTriggeredReferencesResponse",
    "RateEpisodeRequest",
    "RateEpisodeResponse",
    "RatingType",
    "SearchResponse",
    "SettingsResponse",
    "SettingsUpdateRequest",
    "TriggeredReferenceItem",
    "TriggeredReferencesResponse",
    "UpdateEpisodePropertiesRequest",
    "UpdateEpisodePropertiesResponse",
    "UpdateEpisodeRequest",
    "UpdateEpisodeResponse",
]


# ============================================================================
# Triggered References Schemas (kept here - too small to split)
# ============================================================================


class TriggeredReferenceItem(BaseModel):
    """A reference episode triggered by task_type."""

    uuid: str
    name: str
    content: str
    trigger_task_types: list[str]
    display_order: int = 50


class TriggeredReferencesResponse(BaseModel):
    """Response for triggered references lookup."""

    task_type: str
    references: list[TriggeredReferenceItem]
    count: int


class PhaseTriggeredReferenceItem(BaseModel):
    """A reference episode triggered by subtask phase."""

    uuid: str
    name: str
    content: str
    trigger_phases: list[str]
    display_order: int = 50


class PhaseTriggeredReferencesResponse(BaseModel):
    """Response for phase-triggered references lookup."""

    phase: str
    references: list[PhaseTriggeredReferenceItem]
    count: int


# ============================================================================
# Common Schemas (kept here - used across multiple endpoints)
# ============================================================================


class SearchResponse(BaseModel):
    """Response body for memory search."""

    query: str
    results: list[MemorySearchResult]
    count: int


class HealthResponse(BaseModel):
    """Response body for health check."""

    status: str
    database: str
    scope: str | None = None
    scope_id: str | None = None
    total_memories: int | None = None
    error: str | None = None


class MemoryReviewRunRequest(BaseModel):
    """Request one dedicated-agent memory review batch."""

    batch_limit: int = Field(default=25, ge=1, le=100)
    cadence_days: int = Field(default=45, ge=1, le=365)
    reviewer_agent_slug: str = Field(default="memory-curator", min_length=1, max_length=100)
    reviewer_model_id: str | None = Field(default=None, min_length=1, max_length=200)
    dry_run: bool = False
    include_archived: bool = False


class MemoryReviewRunResponse(BaseModel):
    """Result of one dedicated-agent memory review batch."""

    run_id: str | None
    status: str
    reviewed_count: int
    needs_action_count: int
    failed_count: int
    reviewer_agent_slug: str
    reviewer_model_id: str | None = None
    session_id: str | None = None
    errors: list[str] = Field(default_factory=list)


# ============================================================================
# Episode Rating Schemas (ACE-aligned agent citation feedback)
# ============================================================================


class RatingType(StrEnum):
    """Rating type for episode feedback."""

    HELPFUL = "helpful"
    HARMFUL = "harmful"
    USED = "used"


class RateEpisodeRequest(BaseModel):
    """Request to rate an episode."""

    rating: RatingType = Field(..., description="Rating type: helpful, harmful, or used")


class RateEpisodeResponse(BaseModel):
    """Response from rating an episode."""

    success: bool
    uuid: str
    rating: str
    message: str
