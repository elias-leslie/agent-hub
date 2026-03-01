"""Models API - List available models with scores, costs, capabilities, and enrichments."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.constants import MODEL_CATALOG
from app.constants.catalog import SCORE_WEIGHTS

if TYPE_CHECKING:
    from app.constants.catalog import ModelEntry
    from app.models.model_enrichment import ModelEnrichment

router = APIRouter()


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
    timeout_hint_seconds: float = 60.0
    release_date: str | None = None
    knowledge_cutoff: str | None = None
    family: str | None = None
    enrichment: ModelEnrichmentInfo | None = None


class ModelsResponse(BaseModel):
    """Response body for models list."""

    models: list[ModelInfo]
    last_sync: datetime | None = None
    last_model_review: datetime | None = None


def _build_model_info(
    e: ModelEntry,
    enrichment: ModelEnrichment | None = None,
) -> ModelInfo:
    """Build ModelInfo from a catalog entry + optional enrichment.

    For each score dimension, enrichment value takes priority over manual
    catalog value (enrichment > manual fallback). Composite is recomputed
    from the effective scores.
    """
    enr = None
    if enrichment:
        enr = ModelEnrichmentInfo(
            ext_coding=enrichment.ext_coding,
            ext_reasoning=enrichment.ext_reasoning,
            ext_tool_use=enrichment.ext_tool_use,
            ext_planning=enrichment.ext_planning,
            ext_instruction=enrichment.ext_instruction,
            ext_speed_tier=enrichment.ext_speed_tier,
            ext_input_per_m=enrichment.ext_input_per_m,
            ext_output_per_m=enrichment.ext_output_per_m,
            source=enrichment.source,
            synced_at=enrichment.synced_at,
        )

    # Merge scores: enrichment > manual fallback
    coding = (enrichment.ext_coding if enrichment and enrichment.ext_coding is not None else e.scores.coding)
    reasoning = (enrichment.ext_reasoning if enrichment and enrichment.ext_reasoning is not None else e.scores.reasoning)
    tool_use = (enrichment.ext_tool_use if enrichment and enrichment.ext_tool_use is not None else e.scores.tool_use)
    planning = (enrichment.ext_planning if enrichment and enrichment.ext_planning is not None else e.scores.planning)
    instruction = (enrichment.ext_instruction if enrichment and enrichment.ext_instruction is not None else e.scores.instruction)
    design = e.scores.design  # no external source

    composite = round(
        coding * SCORE_WEIGHTS["coding"]
        + reasoning * SCORE_WEIGHTS["reasoning"]
        + planning * SCORE_WEIGHTS["planning"]
        + tool_use * SCORE_WEIGHTS["tool_use"]
        + instruction * SCORE_WEIGHTS["instruction"]
        + design * SCORE_WEIGHTS["design"],
        1,
    )

    return ModelInfo(
        id=e.id, name=e.name, alias=e.alias, hint=e.hint, provider=e.provider,
        scores=ModelScoresInfo(
            coding=coding, reasoning=reasoning,
            planning=planning, tool_use=tool_use,
            instruction=instruction, design=design,
            composite=composite,
        ),
        cost=ModelCostInfo(input_per_m=e.cost.input_per_m, output_per_m=e.cost.output_per_m),
        context_window=e.context_window, speed_tier=e.speed_tier, timeout_hint_seconds=e.timeout_hint_seconds,
        capabilities=ModelCapabilitiesInfo(
            can_generate_images=e.capabilities.can_generate_images,
            has_vision=e.capabilities.has_vision,
            can_edit_images=e.capabilities.can_edit_images,
            has_thinking=e.capabilities.has_thinking,
            supports_pdf=e.capabilities.supports_pdf,
            supports_audio=e.capabilities.supports_audio,
            max_output_tokens=e.capabilities.max_output_tokens,
        ),
        release_date=e.release_date,
        knowledge_cutoff=e.knowledge_cutoff,
        family=e.family,
        enrichment=enr,
    )


@router.get("/models", response_model=ModelsResponse)
async def list_models() -> ModelsResponse:
    """List available models with catalog data + enrichment overlay."""
    from sqlalchemy import func, select

    from app.db import async_session
    from app.models.agent_performance_log import AgentPerformanceLog
    from app.services.model_enrichment_service import get_all_enrichments

    try:
        async with async_session() as db:
            enrichments = await get_all_enrichments(db)
    except Exception:
        enrichments = {}

    models = [
        _build_model_info(e, enrichments.get(e.id))
        for e in MODEL_CATALOG
    ]

    # Determine last sync time from any enrichment
    last_sync = None
    if enrichments:
        synced_times = [e.synced_at for e in enrichments.values() if e.synced_at]
        if synced_times:
            last_sync = max(synced_times)

    # Last model review by persona
    last_model_review = None
    try:
        async with async_session() as db:
            row = await db.execute(
                select(func.max(AgentPerformanceLog.created_at)).where(
                    AgentPerformanceLog.task_type == "model_review",
                    AgentPerformanceLog.logged_by == "persona",
                )
            )
            last_model_review = row.scalar_one_or_none()
    except Exception:
        pass

    return ModelsResponse(models=models, last_sync=last_sync, last_model_review=last_model_review)


@router.post("/models/sync")
async def sync_models() -> dict:
    """Trigger a manual model enrichment sync."""
    from app.db import async_session
    from app.services.model_enrichment_service import sync_all

    async with async_session() as db:
        result = await sync_all(db)

    return result
