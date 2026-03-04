"""Pydantic schemas for the model catalog API endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ModelScoresInfo(BaseModel):
    """Benchmark scores normalized to 0-100."""

    coding: int
    reasoning: int
    planning: int
    tool_use: int
    instruction: int
    design: int
    composite: float


class ModelCostInfo(BaseModel):
    """Pricing in USD per million tokens."""

    input_per_m: float
    output_per_m: float


class ModelCapabilitiesInfo(BaseModel):
    """Model capabilities."""

    can_generate_images: bool
    has_vision: bool
    can_edit_images: bool
    has_thinking: bool = False
    supports_pdf: bool = False
    supports_audio: bool = False
    max_output_tokens: int = 8192


class ModelEnrichmentInfo(BaseModel):
    """External benchmark enrichment data (overlay)."""

    ext_coding: int | None = None
    ext_reasoning: int | None = None
    ext_tool_use: int | None = None
    ext_planning: int | None = None
    ext_instruction: int | None = None
    ext_speed_tier: str | None = None
    ext_input_per_m: float | None = None
    ext_output_per_m: float | None = None
    source: str | None = None
    synced_at: datetime | None = None


class ModelInfo(BaseModel):
    """Full model information."""

    id: str = Field(..., description="Model identifier")
    name: str = Field(..., description="Display name")
    alias: str = Field(..., description="Short alias for @mention")
    hint: str = Field(..., description="Brief UI hint")
    provider: str = Field(..., description="Provider name")
    scores: ModelScoresInfo
    cost: ModelCostInfo
    context_window: int
    speed_tier: str
    capabilities: ModelCapabilitiesInfo
    release_date: str | None = None
    knowledge_cutoff: str | None = None
    family: str | None = None
    enrichment: ModelEnrichmentInfo | None = None


class ModelsResponse(BaseModel):
    """Response body for models list."""

    models: list[ModelInfo]
    providers: dict[str, str] = Field(
        default_factory=dict,
        description="Provider id -> display name for all providers present in models",
    )
    last_sync: datetime | None = None
    last_model_review: datetime | None = None
