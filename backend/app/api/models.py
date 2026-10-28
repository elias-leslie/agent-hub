"""Models API - List available models with scores, costs, capabilities, and enrichments."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, create_model
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
from app.constants.catalog import SCORE_WEIGHTS
from app.constants.models import PROVIDER_NAMES
from app.core.request_actor import current_request_actor
from app.db import get_db
from app.middleware.access_control_auth import require_service_client
from app.routing.model_selection import SelectionRequest
from app.routing.registry import CREDENTIAL_ONLY_PROVIDERS, is_workload_provider
from app.services._enrichment_normalizers import _bare_model_id

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
        routable=is_workload_provider(e.provider) and e.capabilities.supports_chat,
        scores=scores,
        cost=ModelCostInfo(
            input_per_m=input_per_m,
            output_per_m=output_per_m,
            pricing_unit=e.cost.pricing_unit,
            unit_price=e.cost.unit_price,
            cache_read_per_million=e.cost.cache_read_per_million,
            cache_write_per_million=e.cost.cache_write_per_million,
            service_tiers=e.cost.service_tiers,
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
            supports_chat=e.capabilities.supports_chat,
            supports_typed_judgment=e.capabilities.supports_typed_judgment,
            max_state_question_tokens=e.capabilities.max_state_question_tokens,
            thinking_level_map=e.capabilities.thinking_level_map,
        ),
        upstream_id=e.upstream_id,
        access_programs=e.access_programs,
        release_date=e.release_date,
        knowledge_cutoff=e.knowledge_cutoff,
        family=e.family,
        availability=e.availability,
        enrichment=enr,
    )


def _bills_per_token(entry: ModelEntry) -> bool:
    """Subscription and local models have no per-token price to sync."""
    return entry.provider != "local" and "subscription" not in (entry.availability or "")


def _current_discovery(raw: dict[str, Any], known_ids: set[str]) -> CatalogDiscoveryInfo:
    """Drop watchlist samples that were catalogued after the saved sync."""
    discovery = CatalogDiscoveryInfo.model_validate(raw)
    providers = []
    for provider in discovery.top_providers:
        fresh = [model_id for model_id in provider.sample_model_ids if _bare_model_id(model_id) not in known_ids]
        removed = len(provider.sample_model_ids) - len(fresh)
        discovery.unmatched_model_count -= removed
        provider = provider.model_copy(
            update={"sample_model_ids": fresh, "unmatched_count": provider.unmatched_count - removed}
        )
        if provider.unmatched_count > 0:
            providers.append(provider)
    discovery.unmatched_provider_count -= len(discovery.top_providers) - len(providers)
    discovery.top_providers = providers
    discovery.sample_model_ids = [
        model_id for model_id in discovery.sample_model_ids if _bare_model_id(model_id) not in known_ids
    ]
    return discovery


def _build_catalog_health(
    *,
    entries: list[ModelEntry],
    enrichments: dict[str, ModelEnrichment],
    sync_state: ModelEnrichment | object | None,
    last_sync: datetime | None,
    known_ids: set[str] | None = None,
) -> CatalogHealthInfo:
    enriched_models = sum(1 for entry in entries if entry.id in enrichments)
    metered = [entry for entry in entries if _bills_per_token(entry)]
    live_priced_models = sum(
        1
        for entry in metered
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
    known = known_ids if known_ids is not None else {_bare_model_id(entry.id) for entry in entries}
    discovery = _current_discovery(discovery_raw, known) if discovery_raw else None

    return CatalogHealthInfo(
        total_models=len(entries),
        enriched_models=enriched_models,
        unenriched_models=len(entries) - enriched_models,
        models_with_live_pricing=live_priced_models,
        models_missing_live_pricing=len(metered) - live_priced_models,
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
    from app.services.model_catalog_service import (
        get_model_catalog_entries,
        refresh_runtime_model_catalog,
    )
    from app.services.model_enrichment_service import get_all_enrichments, get_catalog_sync_state

    sync_state = None
    try:
        async with async_session() as db:
            await refresh_runtime_model_catalog(db)
            entries = await get_model_catalog_entries(db)
            enrichments = await get_all_enrichments(db)
            sync_state = await get_catalog_sync_state(db)
            models = [_build_model_info(e, enrichments.get(e.id)) for e in entries]
            last_sync = None
            if sync_state and getattr(sync_state, "synced_at", None):
                last_sync = sync_state.synced_at
            elif enrichments:
                synced_times = [e.synced_at for e in enrichments.values() if e.synced_at]
                if synced_times:
                    last_sync = max(synced_times)
            known_ids = {
                _bare_model_id(entry.id)
                for entry in await get_model_catalog_entries(db, active_only=False)
            }
            catalog_health = _build_catalog_health(
                entries=entries,
                enrichments=enrichments,
                sync_state=sync_state,
                last_sync=last_sync,
                known_ids=known_ids,
            )
    except Exception:
        logger.warning("Failed to load model enrichments", exc_info=True)
        from app.constants import MODEL_CATALOG

        entries = list(MODEL_CATALOG)
        enrichments = {}
        models = [_build_model_info(e, None) for e in entries]
        last_sync = None
        catalog_health = _build_catalog_health(
            entries=entries,
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
                )
            )
            last_model_review = row.scalar_one_or_none()
    except Exception:
        logger.debug("Failed to query last model review timestamp", exc_info=True)

    present_providers = {e.provider for e in entries}
    providers = {p: PROVIDER_NAMES.get(p, p.capitalize()) for p in sorted(present_providers)}

    return ModelsResponse(
        models=models,
        providers=providers,
        credential_only_providers={
            p: PROVIDER_NAMES.get(p, p.capitalize()) for p in sorted(CREDENTIAL_ONLY_PROVIDERS)
        },
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


# ---------------------------------------------------------------------------
# Catalog writes: the DB models/model_aliases tables are the only catalog, so
# adding, repricing or retiring a model happens here (never in a migration).
# They need the internal secret and an active registered client, because a
# changed price or alias applies to every caller.
# ---------------------------------------------------------------------------

_MODEL_WRITE_EXCLUDED = {"id", "created_at", "updated_at"}


def _model_row_fields() -> dict[str, Any]:
    from sqlalchemy.dialects.postgresql import JSONB

    from app.models.model_catalog import ModelCatalogEntry

    fields: dict[str, Any] = {}
    for column in ModelCatalogEntry.__table__.columns:
        if column.name in _MODEL_WRITE_EXCLUDED:
            continue
        python_type: Any = dict if isinstance(column.type, JSONB) else column.type.python_type
        fields[column.name] = (python_type | None, None)
    return fields


ModelRowWrite = create_model(
    "ModelRowWrite", __config__=ConfigDict(extra="forbid"), **_model_row_fields()
)


class ModelAliasWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1, max_length=200)
    alias_type: str = Field(default="manual", min_length=1, max_length=50)


@router.put("/models/catalog/{model_id:path}")
async def put_catalog_model(
    model_id: str,
    payload: ModelRowWrite,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Create a catalog model or change the given fields of an existing one."""
    from sqlalchemy.exc import DBAPIError

    await require_service_client(request)

    from app.models.model_catalog import ModelCatalogEntry
    from app.services.model_catalog_service import refresh_runtime_model_catalog

    values = dict(payload.model_dump(exclude_unset=True))
    row = await db.get(ModelCatalogEntry, model_id)
    created = row is None
    if row is None:
        row = ModelCatalogEntry(id=model_id, **{"source": "manual", **values})
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    try:
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail="Model row is missing required fields or invalid") from exc
    await refresh_runtime_model_catalog(db)
    logger.info("Catalog model %s %s by %s", model_id, "created" if created else "updated", current_request_actor() or "unattributed")
    return {"id": model_id, "created": created, "fields": sorted(values)}


@router.put("/models/aliases/{alias}")
async def put_model_alias(
    alias: str,
    payload: ModelAliasWrite,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Point an alias at a catalog model (creating the alias if needed)."""
    await require_service_client(request)
    from app.models.model_catalog import ModelAlias, ModelCatalogEntry
    from app.services.model_catalog_service import refresh_runtime_model_catalog

    if await db.get(ModelCatalogEntry, payload.model_id) is None:
        raise HTTPException(status_code=404, detail="Unknown catalog model")
    key = alias.strip().lower()
    if not key:
        raise HTTPException(status_code=422, detail="Alias is required")
    row = await db.get(ModelAlias, key)
    if row is None:
        db.add(ModelAlias(alias=key, model_id=payload.model_id, alias_type=payload.alias_type, source="manual"))
    else:
        row.model_id = payload.model_id
        row.alias_type = payload.alias_type
    await db.commit()
    await refresh_runtime_model_catalog(db)
    logger.info("Model alias %s -> %s by %s", key, payload.model_id, current_request_actor() or "unattributed")
    return {"alias": key, "model_id": payload.model_id}


@router.post("/models/select")
async def select_model_advice(request: SelectionRequest) -> dict:
    """Select from a generic task type; never accepts task content or executes a model."""
    from app.routing.model_selection import UnknownTaskType, select_model

    catalog = await list_models()
    try:
        result = await select_model(request)
    except UnknownTaskType as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result["catalog_health"] = {
        "is_stale": catalog.catalog_health.is_stale if catalog.catalog_health else None,
        "last_sync": catalog.last_sync.isoformat() if catalog.last_sync else None,
        "last_model_review": catalog.last_model_review.isoformat() if catalog.last_model_review else None,
    }
    return result


@router.get("/models/selection-policy")
async def model_selection_policy() -> dict:
    """List configured task categories for advisory callers."""
    from app.routing.model_selection import selection_policy

    policy = await selection_policy()
    return {"version": policy["version"], "task_types": sorted(policy["policies"])}
