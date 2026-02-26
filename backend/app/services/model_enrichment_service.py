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

# External data source URLs (re-exported for backwards compatibility)
MODELS_DEV_URL = "https://models.dev/api.json"
BENCHMARKS_URL = "https://cdn.jsdelivr.net/gh/arimxyer/models@main/data/benchmarks.json"
BFCL_URL = "https://raw.githubusercontent.com/HuanzhiMao/BFCL-Result/main/2025-12-16/score/data_overall.csv"
LIVEBENCH_URL = "https://raw.githubusercontent.com/LiveBench/livebench.github.io/main/public/table_2026_01_08.csv"

_HTTP_TIMEOUT = 30.0
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
    "sync_all",
]

_ENRICHMENT_FIELDS = [
    "ext_coding", "ext_reasoning", "ext_tool_use", "ext_planning",
    "ext_instruction", "ext_speed_tier", "ext_input_per_m",
    "ext_output_per_m", "raw_benchmark_data",
]


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

    if not any([models_dev_data, benchmark_data, bfcl_data, livebench_data]):
        return {"status": "no_data", "enriched": 0, "total": len(MODEL_CATALOG)}

    enriched_count = 0
    for entry in MODEL_CATALOG:
        result = await enrich_model(
            db, entry.id, models_dev_data, benchmark_data,
            bfcl_data, livebench_data, entry,
        )
        if result:
            enriched_count += 1

    await db.commit()

    logger.info(
        "Model enrichment sync complete: %d/%d enriched",
        enriched_count, len(MODEL_CATALOG),
    )
    return {
        "status": "success",
        "enriched": enriched_count,
        "total": len(MODEL_CATALOG),
        "sources": {
            "models_dev": len(models_dev_data),
            "benchmarks": len(benchmark_data),
            "bfcl": len(bfcl_data),
            "livebench": len(livebench_data),
        },
        "synced_at": datetime.now(UTC).isoformat(),
    }


async def get_all_enrichments(db: AsyncSession) -> dict[str, ModelEnrichment]:
    """Get all enrichments keyed by model_id."""
    result = await db.execute(select(ModelEnrichment))
    return {e.model_id: e for e in result.scalars().all()}
