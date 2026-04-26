"""Memory API schemas - Episode CRUD operations."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.services.memory.memory_models import (
    InjectionTier,
    MemoryApplicability,
    MemoryContextKind,
)
from app.services.memory.service import MemorySource


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
    context_kind: MemoryContextKind | None = Field(
        None,
        description="Semantic channel for this memory (policy, reference, capability, continuity, signal)",
    )
    applicability: MemoryApplicability | None = Field(
        None,
        description="Audience targeting rules for this memory",
    )
    change_reason: str | None = Field(None, description="Why this memory was created")


class AddEpisodeResponse(BaseModel):
    """Response body for add episode."""

    uuid: str = Field(..., description="UUID of the created episode")
    message: str = Field(default="Episode added successfully")


class EpisodeDetailResponse(BaseModel):
    """Response body for single episode details including usage stats."""

    uuid: str
    name: str
    content: str
    injection_tier: str | None = None
    source_description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: int | None = None
    # Properties
    pinned: bool = False
    auto_inject: bool = False
    display_order: int = 50
    trigger_task_types: list[str] = Field(default_factory=list)
    trigger_phases: list[str] = Field(default_factory=list)
    summary: str | None = Field(None, description="Short action phrase for TOON index (~20 chars)")
    review_status: str = "pending"
    sensitivity_tier: str = "normal"
    last_reviewed_at: datetime | None = None
    context_kind: MemoryContextKind = MemoryContextKind.REFERENCE
    applicability: MemoryApplicability = Field(default_factory=MemoryApplicability)
    # Usage stats
    loaded_count: int = 0
    referenced_count: int = 0
    helpful_count: int = 0
    harmful_count: int = 0
    utility_score: float | None = None
    lifecycle_score: float | None = None


class DeleteEpisodeResponse(BaseModel):
    """Response body for episode deletion."""

    success: bool
    episode_id: str
    message: str
    revision_id: str | None = None


class UpdateEpisodeRequest(BaseModel):
    """Request body for in-place episode updates."""

    content: str | None = Field(None, description="Updated content for the episode")
    injection_tier: InjectionTier | None = Field(
        None,
        description="Updated injection tier (mandate/guardrail/reference/archive)",
    )
    change_reason: str | None = Field(None, description="Why this episode was updated")


class UpdateEpisodeResponse(BaseModel):
    """Response body for in-place episode updates."""

    success: bool
    episode_id: str
    injection_tier: str | None = None
    message: str
    version: int | None = None


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
    trigger_phases: list[str] | None = Field(
        None,
        description="Subtask phases that trigger this reference (e.g., ['backend', 'frontend'])",
    )
    context_kind: MemoryContextKind | None = Field(
        None,
        description="Semantic channel for this memory",
    )
    applicability: MemoryApplicability | None = Field(
        None,
        description="Audience targeting rules for this memory",
    )
    summary: str | None = Field(
        None,
        max_length=40,
        description="Short summary for TOON index (~20 chars, e.g., 'use dt for tests')",
    )
    change_reason: str | None = Field(None, description="Why these properties changed")


class UpdateEpisodePropertiesResponse(BaseModel):
    """Response body for episode properties update."""

    success: bool
    episode_id: str
    pinned: bool | None = None
    auto_inject: bool | None = None
    display_order: int | None = None
    trigger_task_types: list[str] | None = None
    trigger_phases: list[str] | None = None
    context_kind: MemoryContextKind | None = None
    applicability: MemoryApplicability | None = None
    summary: str | None = None
    message: str
    version: int | None = None


class MemoryRevisionResponse(BaseModel):
    """Single immutable revision snapshot for a memory episode."""

    id: str
    memory_id: str | None = None
    memory_uuid: str
    version: int
    action: str
    content: str
    name: str | None = None
    summary: str | None = None
    injection_tier: str
    scope: str
    scope_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    changed_by: str | None = None
    change_reason: str | None = None
    content_hash: str
    created_at: datetime


class MemoryRevisionListResponse(BaseModel):
    """Recent immutable revisions for a memory episode."""

    revisions: list[MemoryRevisionResponse]
    total: int


class MemoryRestoreRequest(BaseModel):
    """Restore one memory to a historical revision."""

    change_reason: str | None = None
