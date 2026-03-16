"""Models API - List available models with scores, costs, capabilities, and enrichments."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

# Re-export schemas so existing importers keep working
from app.api.models_catalog_schemas import (
    ModelCapabilitiesInfo,
    ModelCostInfo,
    ModelEnrichmentInfo,
    ModelInfo,
    ModelScoresInfo,
    ModelsResponse,
)
from app.api.models_latency_schemas import LatencyStatsResponse, ModelLatencyStats
from app.constants import MODEL_CATALOG
from app.constants.catalog import SCORE_WEIGHTS
from app.constants.models import PROVIDER_NAMES
from app.db import get_db

if TYPE_CHECKING:
    from app.constants.catalog import ModelEntry
    from app.models.model_enrichment import ModelEnrichment

__all__ = [
    "LatencyStatsResponse",
    "ModelCapabilitiesInfo",
    "ModelCostInfo",
    "ModelEnrichmentInfo",
    "ModelInfo",
    "ModelLatencyStats",
    "ModelScoresInfo",
    "ModelsResponse",
    "router",
]

logger = logging.getLogger(__name__)
router = APIRouter()


def _build_enrichment_info(enrichment: ModelEnrichment) -> ModelEnrichmentInfo:
    """Convert a DB enrichment row into a ModelEnrichmentInfo schema."""
    return ModelEnrichmentInfo(
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


def _merge_scores(
    e: ModelEntry,
    enrichment: ModelEnrichment | None,
) -> ModelScoresInfo:
    """Merge catalog scores with enrichment overrides and compute composite."""
    coding = enrichment.ext_coding if enrichment and enrichment.ext_coding is not None else e.scores.coding
    reasoning = enrichment.ext_reasoning if enrichment and enrichment.ext_reasoning is not None else e.scores.reasoning
    tool_use = enrichment.ext_tool_use if enrichment and enrichment.ext_tool_use is not None else e.scores.tool_use
    planning = enrichment.ext_planning if enrichment and enrichment.ext_planning is not None else e.scores.planning
    instruction = enrichment.ext_instruction if enrichment and enrichment.ext_instruction is not None else e.scores.instruction
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
    return ModelScoresInfo(
        coding=coding,
        reasoning=reasoning,
        planning=planning,
        tool_use=tool_use,
        instruction=instruction,
        design=design,
        composite=composite,
    )


def _build_model_info(
    e: ModelEntry,
    enrichment: ModelEnrichment | None = None,
) -> ModelInfo:
    """Build ModelInfo from a catalog entry + optional enrichment.

    Enrichment values take priority over manual catalog values.
    """
    enr = _build_enrichment_info(enrichment) if enrichment else None
    scores = _merge_scores(e, enrichment)

    return ModelInfo(
        id=e.id,
        name=e.name,
        alias=e.alias,
        hint=e.hint,
        provider=e.provider,
        scores=scores,
        cost=ModelCostInfo(input_per_m=e.cost.input_per_m, output_per_m=e.cost.output_per_m),
        context_window=e.context_window,
        speed_tier=e.speed_tier,
        capabilities=ModelCapabilitiesInfo(
            can_generate_images=e.capabilities.can_generate_images,
            has_vision=e.capabilities.has_vision,
            can_edit_images=e.capabilities.can_edit_images,
            has_thinking=e.capabilities.has_thinking,
            supports_pdf=e.capabilities.supports_pdf,
            supports_audio=e.capabilities.supports_audio,
            supports_tool_execution=e.capabilities.supports_tool_execution,
            supports_verbosity=e.capabilities.supports_verbosity,
            supports_xhigh=e.capabilities.supports_xhigh,
            supports_session_cache=e.capabilities.supports_session_cache,
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
        logger.warning("Failed to load model enrichments", exc_info=True)
        enrichments = {}

    models = [_build_model_info(e, enrichments.get(e.id)) for e in MODEL_CATALOG]

    last_sync = None
    if enrichments:
        synced_times = [e.synced_at for e in enrichments.values() if e.synced_at]
        if synced_times:
            last_sync = max(synced_times)

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
        logger.debug("Failed to query last model review timestamp", exc_info=True)

    present_providers = {e.provider for e in MODEL_CATALOG}
    providers = {p: PROVIDER_NAMES.get(p, p.capitalize()) for p in sorted(present_providers)}

    return ModelsResponse(
        models=models,
        providers=providers,
        last_sync=last_sync,
        last_model_review=last_model_review,
    )


@router.post("/models/sync")
async def sync_models() -> dict:
    """Trigger a manual model enrichment sync."""
    from app.db import async_session
    from app.services.model_enrichment_service import sync_all

    async with async_session() as db:
        result = await sync_all(db)

    return result


@router.get("/models/latency-stats", response_model=LatencyStatsResponse)
async def get_latency_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    days: Annotated[int, Query(ge=1, le=90)] = 7,
    min_samples: Annotated[int, Query(ge=1, le=1000)] = 10,
) -> LatencyStatsResponse:
    """Get per-model latency percentiles."""
    from app.services.latency_stats import get_model_latency_stats

    raw_stats = await get_model_latency_stats(db, days=days, min_samples=min_samples)

    stats = [
        ModelLatencyStats(
            model=s["model"],
            sample_count=s["sample_count"],
            p50_ms=s["p50_ms"],
            p95_ms=s["p95_ms"],
            p99_ms=s["p99_ms"],
        )
        for s in raw_stats
    ]

    return LatencyStatsResponse(stats=stats)
