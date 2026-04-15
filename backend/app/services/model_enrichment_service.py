"""Model enrichment service — fetches external benchmark/pricing data.

Enriches the static MODEL_CATALOG with data from:
- models.dev API (model metadata + pricing)
- arimxyer/models benchmarks.json (coding, reasoning, instruction)
- BFCL leaderboard (tool_use / function calling accuracy)
- LiveBench (planning / reasoning tasks, instruction following)

Stores enrichments in model_enrichments DB table as an overlay.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import MODEL_CATALOG
from app.constants.models import PROVIDER_NAMES
from app.models.model_catalog_sync_state import ModelCatalogSyncState
from app.models.model_enrichment import ModelEnrichment
from app.services._enrichment_fetchers import (
    fetch_benchmarks,
    fetch_bfcl,
    fetch_livebench,
    fetch_models_dev,
)
from app.services._enrichment_matchers import _match_model
from app.services._enrichment_normalizers import (
    _bare_model_id,
    _livebench_avg,
    _livebench_category_avg,
    _normalize_arimxyer_index,
    _normalize_bfcl_name,
    _normalize_livebench_name,
    _normalize_score,
    _parse_pct,
    _parse_price,
)

if TYPE_CHECKING:
    from app.constants.catalog import ModelEntry

logger = logging.getLogger(__name__)

_ARIMXYER_INDEX_SCALE = 57.0
_LIVEBENCH_REASONING_TASKS = [
    "zebra_puzzle", "spatial", "connections", "consecutive_events",
    "logic_with_navigation", "theory_of_mind",
]
_LIVEBENCH_IF_TASKS = [
    "paraphrase", "story_generation", "summarize", "simplify",
]

# Re-export private helpers used by callers or tests
__all__ = [
    "_bare_model_id",
    "_build_discovery_summary",
    "_livebench_avg",
    "_livebench_category_avg",
    "_match_model",
    "_normalize_arimxyer_index",
    "_normalize_bfcl_name",
    "_normalize_livebench_name",
    "_normalize_score",
    "_parse_pct",
    "_parse_price",
    "enrich_model",
    "fetch_benchmarks",
    "fetch_bfcl",
    "fetch_livebench",
    "fetch_models_dev",
    "get_all_enrichments",
    "get_catalog_sync_state",
    "sync_all",
]

_ENRICHMENT_FIELDS = [
    "ext_coding", "ext_reasoning", "ext_tool_use", "ext_planning",
    "ext_instruction", "ext_speed_tier", "ext_input_per_m",
    "ext_output_per_m", "raw_benchmark_data",
]

_SYNC_STATE_ID = 1
_DISCOVERY_PROVIDER_ALIASES: dict[str, set[str]] = {
    "claude": {"anthropic", "claude"},
    "cloudflare": {"cloudflare", "workersai"},
    "gemini": {"gemini", "google", "googleaistudio", "googledeepmind"},
    "minimax": {"minimax"},
    "nvidia": {"nim", "nvidia"},
    "openai": {"openai"},
    "xai": {"xai"},
    "zhipu": {"bigmodel", "zai", "zhipu"},
}


def _provider_meta(dev_entry: dict[str, Any]) -> tuple[str, str]:
    provider_id = str(dev_entry.get("provider_id") or dev_entry.get("provider") or "unknown").strip() or "unknown"
    provider_name = str(dev_entry.get("provider_name") or provider_id).strip() or provider_id
    return provider_id, provider_name


def _normalize_provider_key(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _canonical_catalog_provider(dev_entry: dict[str, Any]) -> str | None:
    provider_id, provider_name = _provider_meta(dev_entry)
    normalized_keys = {
        _normalize_provider_key(provider_id),
        _normalize_provider_key(provider_name),
    }
    for provider, aliases in _DISCOVERY_PROVIDER_ALIASES.items():
        if normalized_keys & aliases:
            return provider
    return None


def _build_discovery_summary(models_dev_data: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize unmatched external models for providers we already track."""
    catalog_ids = {_bare_model_id(entry.id) for entry in MODEL_CATALOG}
    matched_catalog_providers: set[str] = set()

    for dev_entry in models_dev_data:
        model_id = str(dev_entry.get("id") or "").strip()
        if not model_id or model_id not in catalog_ids:
            continue
        canonical_provider = _canonical_catalog_provider(dev_entry)
        if canonical_provider is not None:
            matched_catalog_providers.add(canonical_provider)

    grouped: dict[str, dict[str, Any]] = {}
    seen_ids: set[str] = set()
    for dev_entry in models_dev_data:
        model_id = str(dev_entry.get("id") or "").strip()
        if not model_id or model_id in catalog_ids or model_id in seen_ids:
            continue
        canonical_provider = _canonical_catalog_provider(dev_entry)
        if canonical_provider is None or canonical_provider not in matched_catalog_providers:
            continue
        provider_name = PROVIDER_NAMES.get(canonical_provider, canonical_provider.capitalize())
        seen_ids.add(model_id)
        bucket = grouped.setdefault(
            canonical_provider,
            {
                "provider_id": canonical_provider,
                "provider_name": provider_name,
                "unmatched_count": 0,
                "sample_model_ids": [],
            },
        )
        bucket["unmatched_count"] += 1
        if len(bucket["sample_model_ids"]) < 5:
            bucket["sample_model_ids"].append(model_id)

    top_providers = sorted(
        grouped.values(),
        key=lambda item: (-int(item["unmatched_count"]), str(item["provider_name"]).lower()),
    )[:8]

    sample_model_ids: list[str] = []
    for bucket in top_providers:
        for model_id in bucket["sample_model_ids"]:
            if model_id not in sample_model_ids:
                sample_model_ids.append(model_id)
            if len(sample_model_ids) >= 12:
                break
        if len(sample_model_ids) >= 12:
            break

    return {
        "unmatched_model_count": sum(int(item["unmatched_count"]) for item in grouped.values()),
        "unmatched_provider_count": len(grouped),
        "top_providers": top_providers,
        "sample_model_ids": sample_model_ids,
    }


async def _upsert_catalog_sync_state(
    db: AsyncSession,
    *,
    status: str,
    source_counts: dict[str, int],
    discovery_summary: dict[str, Any],
    synced_at: datetime,
    error: str | None = None,
) -> None:
    state = await db.get(ModelCatalogSyncState, _SYNC_STATE_ID)
    if state is None:
        state = ModelCatalogSyncState(id=_SYNC_STATE_ID)
        db.add(state)

    state.status = status
    state.source_counts = source_counts
    state.discovery_summary = discovery_summary
    state.synced_at = synced_at
    state.error = error


async def enrich_model(
    db: AsyncSession,
    model_id: str,
    models_dev_data: list[dict[str, Any]],
    benchmark_data: list[dict[str, Any]],
    bfcl_data: list[dict[str, Any]],
    livebench_data: list[dict[str, Any]],
    catalog_entry: ModelEntry,
) -> ModelEnrichment | None:
    """Enrich a single model and upsert to DB."""
    matched = _match_model(
        model_id, models_dev_data, benchmark_data,
        bfcl_data, livebench_data, catalog_entry,
    )
    if not matched:
        return None

    result = await db.execute(
        select(ModelEnrichment).where(ModelEnrichment.model_id == model_id)
    )
    enrichment = result.scalar_one_or_none()
    now = datetime.now(UTC)

    if enrichment:
        for f in _ENRICHMENT_FIELDS:
            if f in matched:
                setattr(enrichment, f, matched[f])
        enrichment.synced_at = now
    else:
        enrichment = ModelEnrichment(
            model_id=model_id,
            **{f: matched.get(f) for f in _ENRICHMENT_FIELDS},
            source="models.dev+benchmarks+bfcl+livebench",
            synced_at=now,
        )
        db.add(enrichment)

    return enrichment


async def _fetch_all_sources() -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Fetch from all 4 external sources (best-effort, any failure is non-fatal)."""
    models_dev_data: list[dict[str, Any]] = []
    benchmark_data: list[dict[str, Any]] = []
    bfcl_data: list[dict[str, Any]] = []
    livebench_data: list[dict[str, Any]] = []

    try:
        models_dev_data = await fetch_models_dev()
        logger.info("Fetched %d entries from models.dev", len(models_dev_data))
    except Exception as e:
        logger.warning("Failed to fetch models.dev data: %s", e)

    try:
        benchmark_data = await fetch_benchmarks()
        logger.info("Fetched %d entries from arimxyer benchmarks", len(benchmark_data))
    except Exception as e:
        logger.warning("Failed to fetch benchmark data: %s", e)

    try:
        bfcl_data = await fetch_bfcl()
        logger.info("Fetched %d entries from BFCL", len(bfcl_data))
    except Exception as e:
        logger.warning("Failed to fetch BFCL data: %s", e)

    try:
        livebench_data = await fetch_livebench()
        logger.info("Fetched %d entries from LiveBench", len(livebench_data))
    except Exception as e:
        logger.warning("Failed to fetch LiveBench data: %s", e)

    return models_dev_data, benchmark_data, bfcl_data, livebench_data


async def sync_all(db: AsyncSession) -> dict[str, Any]:
    """Sync all catalog models with external data sources.

    Fetches from all 4 sources, matches against MODEL_CATALOG, and upserts.
    """
    models_dev_data, benchmark_data, bfcl_data, livebench_data = await _fetch_all_sources()

    source_counts = {
        "models_dev": len(models_dev_data),
        "benchmarks": len(benchmark_data),
        "bfcl": len(bfcl_data),
        "livebench": len(livebench_data),
    }
    discovery_summary = _build_discovery_summary(models_dev_data)

    if not any(source_counts.values()):
        return {
            "status": "no_data",
            "enriched": 0,
            "total": len(MODEL_CATALOG),
            "sources": source_counts,
            "discovery": discovery_summary,
        }

    enriched_count = 0
    for entry in MODEL_CATALOG:
        result = await enrich_model(
            db, entry.id, models_dev_data, benchmark_data,
            bfcl_data, livebench_data, entry,
        )
        if result:
            enriched_count += 1

    now = datetime.now(UTC)
    await _upsert_catalog_sync_state(
        db,
        status="success",
        source_counts=source_counts,
        discovery_summary=discovery_summary,
        synced_at=now,
    )
    await db.commit()

    logger.info(
        "Model enrichment sync complete: %d/%d enriched",
        enriched_count, len(MODEL_CATALOG),
    )
    return {
        "status": "success",
        "enriched": enriched_count,
        "total": len(MODEL_CATALOG),
        "sources": source_counts,
        "discovery": discovery_summary,
        "synced_at": now.isoformat(),
    }


async def get_all_enrichments(db: AsyncSession) -> dict[str, ModelEnrichment]:
    """Get all enrichments keyed by model_id."""
    result = await db.execute(select(ModelEnrichment))
    return {e.model_id: e for e in result.scalars().all()}


async def get_catalog_sync_state(db: AsyncSession) -> ModelCatalogSyncState | None:
    """Return persisted state for the last catalog sync run."""
    return await db.get(ModelCatalogSyncState, _SYNC_STATE_ID)
