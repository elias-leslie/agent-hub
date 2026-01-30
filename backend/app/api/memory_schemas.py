"""Memory API schemas - Request/response models."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.services.memory.service import (
    MemorySearchResult,
    MemorySource,
)
from app.services.memory.types import InjectionTier

# ============================================================================
# Settings Schemas
# ============================================================================


class SettingsResponse(BaseModel):
    """Response schema for memory settings."""

    enabled: bool = Field(..., description="Kill switch for memory injection (False = no memories)")
    budget_enabled: bool = Field(..., description="Budget enforcement toggle")
    total_budget: int = Field(..., description="Total token budget when budget_enabled=True")
    max_mandates: int = Field(0, description="Max mandates to inject (0 = unlimited)")
    max_guardrails: int = Field(0, description="Max guardrails to inject (0 = unlimited)")
    reference_index_enabled: bool = Field(
        True, description="Include TOON reference index for discoverability"
    )


class SettingsUpdateRequest(BaseModel):
    """Request schema for updating memory settings."""

    enabled: bool | None = Field(None, description="Kill switch for memory injection")
    budget_enabled: bool | None = Field(None, description="Budget enforcement toggle")
    total_budget: int | None = Field(None, ge=100, le=100000, description="Total token budget")
    max_mandates: int | None = Field(None, ge=0, le=100, description="Max mandates (0 = unlimited)")
    max_guardrails: int | None = Field(
        None, ge=0, le=100, description="Max guardrails (0 = unlimited)"
    )
    reference_index_enabled: bool | None = Field(None, description="Include TOON reference index")


class BudgetUsageResponse(BaseModel):
    """Response schema for budget usage statistics."""

    mandates_tokens: int = Field(..., description="Tokens used by mandates")
    guardrails_tokens: int = Field(..., description="Tokens used by guardrails")
    reference_tokens: int = Field(..., description="Tokens used by reference")
    total_tokens: int = Field(..., description="Total tokens used")
    total_budget: int = Field(..., description="Configured budget limit")
    remaining: int = Field(..., description="Tokens remaining in budget")
    hit_limit: bool = Field(..., description="Whether budget limit was reached")
    # Count fields for coverage tracking
    mandates_injected: int = Field(0, description="Number of mandates injected")
    mandates_total: int = Field(0, description="Total mandates in memory")
    guardrails_injected: int = Field(0, description="Number of guardrails injected")
    guardrails_total: int = Field(0, description="Total guardrails in memory")
    reference_injected: int = Field(0, description="Number of reference items injected")
    reference_total: int = Field(0, description="Total reference items in memory")


# ============================================================================
# Triggered References Schemas
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


# ============================================================================
# Episode CRUD Schemas
# ============================================================================


class AddEpisodeRequest(BaseModel):
    """Request body for adding an episode to memory."""

    content: str = Field(..., description="Content to remember")
    source: MemorySource = Field(MemorySource.CHAT, description="Source type (chat, voice, system)")
    source_description: str | None = Field(None, description="Human-readable source description")
    reference_time: datetime | None = Field(
        None, description="When the episode occurred (defaults to now)"
    )
    injection_tier: InjectionTier | None = Field(
        None,
        description="Injection tier (mandate/guardrail/reference). If not specified, uses source_description.",
    )
    preserve_stats_from: str | None = Field(
        None,
        description="UUID of episode to copy usage stats from (for edit flows)",
    )


class AddEpisodeResponse(BaseModel):
    """Response body for add episode."""

    uuid: str = Field(..., description="UUID of the created episode")
    message: str = Field(default="Episode added successfully")


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


class EpisodeDetailResponse(BaseModel):
    """Response body for single episode details including usage stats."""

    uuid: str
    name: str
    content: str
    injection_tier: str | None = None
    source_description: str | None = None
    created_at: datetime | None = None
    # Properties
    pinned: bool = False
    auto_inject: bool = False
    display_order: int = 50
    trigger_task_types: list[str] = Field(default_factory=list)
    summary: str | None = Field(None, description="Short action phrase for TOON index (~20 chars)")
    # Usage stats from Neo4j
    loaded_count: int = 0
    referenced_count: int = 0
    helpful_count: int = 0
    harmful_count: int = 0
    utility_score: float | None = None


class DeleteEpisodeResponse(BaseModel):
    """Response body for episode deletion."""

    success: bool
    episode_id: str
    message: str


class UpdateEpisodeTierRequest(BaseModel):
    """Request body for updating episode injection tier."""

    injection_tier: InjectionTier = Field(..., description="New tier (mandate/guardrail/reference)")


class UpdateEpisodeTierResponse(BaseModel):
    """Response body for episode tier update."""

    success: bool
    episode_id: str
    injection_tier: str
    message: str


class UpdateEpisodePropertiesRequest(BaseModel):
    """Request body for updating episode properties."""

    pinned: bool | None = Field(None, description="Pin episode to prevent demotion")
    auto_inject: bool | None = Field(None, description="Auto-inject reference in every session")
    display_order: int | None = Field(
        None, ge=1, le=99, description="Injection order (1-99, lower = earlier, default 50)"
    )
    trigger_task_types: list[str] | None = Field(
        None, description="Task types that trigger this reference (e.g., ['database', 'migration'])"
    )
    summary: str | None = Field(
        None,
        max_length=50,
        description="Short summary for TOON index (~20 chars, e.g., 'use dt for tests')",
    )


class UpdateEpisodePropertiesResponse(BaseModel):
    """Response body for episode properties update."""

    success: bool
    episode_id: str
    pinned: bool | None = None
    auto_inject: bool | None = None
    display_order: int | None = None
    trigger_task_types: list[str] | None = None
    summary: str | None = None
    message: str


# ============================================================================
# Bulk Operation Schemas
# ============================================================================


class BulkUpdateTierRequest(BaseModel):
    """Request body for bulk tier updates."""

    updates: list[dict[str, str]] = Field(
        ...,
        min_length=1,
        description="List of {uuid, tier} objects",
        examples=[
            [{"uuid": "abc-123", "tier": "mandate"}, {"uuid": "def-456", "tier": "guardrail"}]
        ],
    )


class BulkUpdateTierError(BaseModel):
    """Error detail for a single failed update."""

    uuid: str
    error: str


class BulkUpdateTierResponse(BaseModel):
    """Response body for bulk tier update."""

    updated: int = Field(..., description="Number of successfully updated episodes")
    failed: int = Field(..., description="Number of failed updates")
    errors: list[BulkUpdateTierError] = Field(default_factory=list)


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


class BatchUpdateTierItem(BaseModel):
    """Single item for batch tier update."""

    uuid: str = Field(..., description="Episode UUID or 8-char prefix")
    tier: InjectionTier = Field(..., description="New tier")


class BatchUpdateTierRequest(BaseModel):
    """Request body for batch tier update."""

    updates: list[BatchUpdateTierItem] = Field(
        ..., min_length=1, max_length=500, description="List of (uuid, tier) updates"
    )


class BatchUpdateTierResult(BaseModel):
    """Result for a single episode update."""

    uuid: str
    success: bool
    error: str | None = None


class BatchUpdateTierResponse(BaseModel):
    """Response body for batch tier update."""

    results: list[BatchUpdateTierResult]
    updated: int
    failed: int
    total: int


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
    """Response body for orphaned edge cleanup."""

    edges_updated: int = Field(..., description="Edges with stale refs updated")
    edges_deleted: int = Field(..., description="Fully orphaned edges deleted")
    stale_refs_removed: int = Field(..., description="Total stale episode refs removed")
    error: str | None = None


# ============================================================================
# Episode Rating Schemas (ACE-aligned agent citation feedback)
# ============================================================================


class RatingType(str, Enum):
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
