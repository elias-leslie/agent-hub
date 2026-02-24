"""Memory API schemas - Episode CRUD operations."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.services.memory.memory_models import InjectionTier
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
    # Properties
    pinned: bool = False
    auto_inject: bool = False
    display_order: int = 50
    trigger_task_types: list[str] = Field(default_factory=list)
    summary: str | None = Field(None, description="Short action phrase for TOON index (~20 chars)")
    # Usage stats
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
    trigger_phases: list[str] | None = None
    summary: str | None = None
    message: str
