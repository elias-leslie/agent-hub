"""Models API - List available models with scores, costs, capabilities, and enrichments."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import MODEL_CATALOG
from app.constants.catalog import MODEL_CATALOG_BY_ID, SCORE_WEIGHTS
from app.constants.models import PROVIDER_NAMES
from app.db import get_db

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
    providers: dict[str, str] = Field(default_factory=dict, description="Provider id → display name for all providers present in models")
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

    # Build provider map for only the providers present in the catalog
    present_providers = {e.provider for e in MODEL_CATALOG}
    providers = {p: PROVIDER_NAMES.get(p, p.capitalize()) for p in sorted(present_providers)}

    return ModelsResponse(models=models, providers=providers, last_sync=last_sync, last_model_review=last_model_review)


@router.post("/models/sync")
async def sync_models() -> dict:
    """Trigger a manual model enrichment sync."""
    from app.db import async_session
    from app.services.model_enrichment_service import sync_all

    async with async_session() as db:
        result = await sync_all(db)

    return result


class ModelLatencyStats(BaseModel):
    """Per-model latency percentile statistics."""

    model: str
    sample_count: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    adaptive_timeout_seconds: float


class LatencyStatsResponse(BaseModel):
    """Response for latency stats endpoint."""

    stats: list[ModelLatencyStats]


@router.get("/models/latency-stats", response_model=LatencyStatsResponse)
async def get_latency_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    days: Annotated[int, Query(ge=1, le=90)] = 7,
    min_samples: Annotated[int, Query(ge=1, le=1000)] = 10,
) -> LatencyStatsResponse:
    """Get per-model latency percentiles with adaptive timeout suggestions."""
    from app.services.latency_stats import get_model_latency_stats

    raw_stats = await get_model_latency_stats(db, days=days, min_samples=min_samples)

    stats = []
    for s in raw_stats:
        entry = MODEL_CATALOG_BY_ID.get(s["model"])
        catalog_floor = entry.timeout_hint_seconds if entry else 60.0
        adaptive = max(catalog_floor, min(s["p95_ms"] / 1000 * 1.5, 600.0))
        stats.append(ModelLatencyStats(
            model=s["model"],
            sample_count=s["sample_count"],
            p50_ms=s["p50_ms"],
            p95_ms=s["p95_ms"],
            p99_ms=s["p99_ms"],
            adaptive_timeout_seconds=round(adaptive, 1),
        ))

    return LatencyStatsResponse(stats=stats)


@router.post("/models/sync-timeouts")
async def sync_timeouts(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Compute and cache adaptive timeouts in Redis from observed latency data."""
    from app.services.adaptive_timeout import update_adaptive_timeouts
    from app.services.latency_stats import get_model_latency_stats

    stats = await get_model_latency_stats(db, days=7, min_samples=10)
    count = await update_adaptive_timeouts(stats)
    return {"updated": count, "models": [s["model"] for s in stats]}
