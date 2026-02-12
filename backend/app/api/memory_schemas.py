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
    OrphanedCleanupResponse,
)

# Re-export episode CRUD schemas
from .memory_schemas_episodes import (
    AddEpisodeRequest,
    AddEpisodeResponse,
    DeleteEpisodeResponse,
    EpisodeDetailResponse,
    UpdateEpisodePropertiesRequest,
    UpdateEpisodePropertiesResponse,
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
    "OrphanedCleanupResponse",
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
    neo4j: str
    scope: str | None = None
    scope_id: str | None = None
    error: str | None = None


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
