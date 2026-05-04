"""Models API - List available models with scores, costs, capabilities, and enrichments."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

# Re-export schemas so existing importers keep working
from app.api.models_catalog_schemas import (
    CatalogDiscoveryInfo,
    CatalogHealthInfo,
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
    "CatalogHealthInfo",
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
_CATALOG_STALE_AFTER_HOURS = 24


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
    input_per_m = enrichment.ext_input_per_m if enrichment and enrichment.ext_input_per_m is not None else e.cost.input_per_m
    output_per_m = enrichment.ext_output_per_m if enrichment and enrichment.ext_output_per_m is not None else e.cost.output_per_m
    speed_tier = enrichment.ext_speed_tier if enrichment and enrichment.ext_speed_tier is not None else e.speed_tier
    cost_source = "enrichment" if enrichment and (
        enrichment.ext_input_per_m is not None or enrichment.ext_output_per_m is not None
    ) else "catalog"

    return ModelInfo(
        id=e.id,
        name=e.name,
        alias=e.alias,
        hint=e.hint,
        provider=e.provider,
        scores=scores,
        cost=ModelCostInfo(
            input_per_m=input_per_m,
            output_per_m=output_per_m,
            pricing_unit=e.cost.pricing_unit,
            unit_price=e.cost.unit_price,
            source=cost_source,
        ),
        context_window=e.context_window,
        speed_tier=speed_tier,
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
        availability=e.availability,
        enrichment=enr,
    )


def _build_catalog_health(
    *,
    enrichments: dict[str, ModelEnrichment],
    sync_state: ModelEnrichment | object | None,
    last_sync: datetime | None,
) -> CatalogHealthInfo:
    enriched_models = sum(1 for entry in MODEL_CATALOG if entry.id in enrichments)
    live_priced_models = sum(
        1
        for entry in MODEL_CATALOG
        if (
            (enrichment := enrichments.get(entry.id)) is not None
            and (enrichment.ext_input_per_m is not None or enrichment.ext_output_per_m is not None)
        )
    )
    is_stale = (
        last_sync is None
        or datetime.now(UTC) - last_sync > timedelta(hours=_CATALOG_STALE_AFTER_HOURS)
    )
    source_counts = getattr(sync_state, "source_counts", None)
    discovery_raw = getattr(sync_state, "discovery_summary", None)
    discovery = CatalogDiscoveryInfo.model_validate(discovery_raw or {}) if discovery_raw else None

    return CatalogHealthInfo(
        total_models=len(MODEL_CATALOG),
        enriched_models=enriched_models,
        unenriched_models=len(MODEL_CATALOG) - enriched_models,
        models_with_live_pricing=live_priced_models,
        models_missing_live_pricing=len(MODEL_CATALOG) - live_priced_models,
        is_stale=is_stale,
        stale_after_hours=_CATALOG_STALE_AFTER_HOURS,
        sync_status=getattr(sync_state, "status", None),
        sync_error=getattr(sync_state, "error", None),
        source_counts=source_counts if isinstance(source_counts, dict) else None,
        discovery=discovery,
    )


@router.get("/models", response_model=ModelsResponse)
async def list_models() -> ModelsResponse:
    """List available models with catalog data + enrichment overlay."""
    from sqlalchemy import func, select

    from app.db import async_session
    from app.models.agent_performance_log import AgentPerformanceLog
    from app.services.model_enrichment_service import get_all_enrichments, get_catalog_sync_state

    sync_state = None
    try:
        async with async_session() as db:
            enrichments = await get_all_enrichments(db)
            sync_state = await get_catalog_sync_state(db)
            models = [_build_model_info(e, enrichments.get(e.id)) for e in MODEL_CATALOG]
            last_sync = None
            if sync_state and getattr(sync_state, "synced_at", None):
                last_sync = sync_state.synced_at
            elif enrichments:
                synced_times = [e.synced_at for e in enrichments.values() if e.synced_at]
                if synced_times:
                    last_sync = max(synced_times)
            catalog_health = _build_catalog_health(
                enrichments=enrichments,
                sync_state=sync_state,
                last_sync=last_sync,
            )
    except Exception:
        logger.warning("Failed to load model enrichments", exc_info=True)
        enrichments = {}
        models = [_build_model_info(e, None) for e in MODEL_CATALOG]
        last_sync = None
        catalog_health = _build_catalog_health(
            enrichments=enrichments,
            sync_state=sync_state,
            last_sync=last_sync,
        )

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
        catalog_health=catalog_health,
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
