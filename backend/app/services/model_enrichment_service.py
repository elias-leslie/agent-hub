"""Model enrichment service — fetches external benchmark/pricing data.

Enriches the static MODEL_CATALOG with data from:
- models.dev API (model metadata + pricing)
- jsdelivr benchmarks.json (benchmark scores)

Stores enrichments in model_enrichments DB table as an overlay.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import MODEL_CATALOG
from app.models.model_enrichment import ModelEnrichment

logger = logging.getLogger(__name__)

# External data sources
MODELS_DEV_URL = "https://models.dev/api.json"
BENCHMARKS_URL = "https://cdn.jsdelivr.net/gh/arimxyer/models@main/data/benchmarks.json"

# HTTP timeout
_HTTP_TIMEOUT = 30.0


async def fetch_models_dev() -> list[dict[str, Any]]:
    """Fetch model catalog from models.dev API.

    The API returns {provider_key: {models: {model_id: model_data}}}.
    We flatten this into a list of model dicts with an ``id`` field.

    Returns:
        Flat list of model entries across all providers.
    """
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(MODELS_DEV_URL)
        resp.raise_for_status()
        data = resp.json()

    if isinstance(data, list):
        return data

    # Flatten nested provider → models structure
    flat: list[dict[str, Any]] = []
    for provider_data in data.values():
        if not isinstance(provider_data, dict):
            continue
        models = provider_data.get("models", {})
        if not isinstance(models, dict):
            continue
        for model_id, model_data in models.items():
            if isinstance(model_data, dict):
                model_data.setdefault("id", model_id)
                flat.append(model_data)
    return flat


async def fetch_benchmarks() -> list[dict[str, Any]]:
    """Fetch benchmark data from jsdelivr.

    Returns:
        List of benchmark entries.
    """
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(BENCHMARKS_URL)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return data.get("benchmarks", data.get("data", []))


def _bare_model_id(model_id: str) -> str:
    """Strip provider prefix from a catalog model_id.

    ``openai/gpt-5.2`` → ``gpt-5.2``, ``claude-sonnet-4-6`` → ``claude-sonnet-4-6``.
    """
    return model_id.rsplit("/", 1)[-1]


def _find_in_models_dev(
    bare_id: str, models_dev_data: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Find a models.dev entry by exact ``id`` match against bare model ID."""
    for entry in models_dev_data:
        ext_id = entry.get("id", "")
        if not ext_id:
            continue
        if bare_id == ext_id:
            return entry
    return None


def _find_in_benchmarks(
    bare_id: str, benchmark_data: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Find a benchmark entry by ``slug`` match.

    Tries exact match, then strips ``-preview`` suffix for Gemini-style IDs.
    """
    for entry in benchmark_data:
        slug = entry.get("slug", "")
        if not slug:
            continue
        if bare_id == slug:
            return entry

    # Retry without -preview suffix (e.g. gemini-3-flash-preview → gemini-3-flash)
    stripped = bare_id.removesuffix("-preview")
    if stripped != bare_id:
        for entry in benchmark_data:
            slug = entry.get("slug", "")
            if not slug:
                continue
            if stripped == slug:
                return entry

    return None


def _match_model(
    model_id: str,
    models_dev_data: list[dict[str, Any]],
    benchmark_data: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Match a catalog model_id to external data sources.

    Uses exact ID matching against the fields each source actually provides:
    - models.dev: ``id`` field on flattened model entries
    - benchmarks: ``slug`` field (with ``-preview`` suffix stripping)

    Returns:
        Dict with enrichment fields, or None if no match found.
    """
    bare_id = _bare_model_id(model_id)
    enrichment: dict[str, Any] = {}
    raw: dict[str, Any] = {}

    # Match in models.dev data (by id)
    dev_entry = _find_in_models_dev(bare_id, models_dev_data)
    if dev_entry:
        raw["models_dev"] = dev_entry
        # Extract pricing — models.dev uses "cost" with per-million values
        cost = dev_entry.get("cost", {})
        if cost:
            if "input" in cost:
                enrichment["ext_input_per_m"] = _parse_price(cost["input"])
            if "output" in cost:
                enrichment["ext_output_per_m"] = _parse_price(cost["output"])
        # Extract speed info
        if dev_entry.get("output_tps"):
            tps = dev_entry["output_tps"]
            if tps >= 100:
                enrichment["ext_speed_tier"] = "fast"
            elif tps >= 40:
                enrichment["ext_speed_tier"] = "medium"
            else:
                enrichment["ext_speed_tier"] = "slow"

    # Match in benchmark data (by slug)
    bench_entry = _find_in_benchmarks(bare_id, benchmark_data)
    if bench_entry:
        raw["benchmarks"] = bench_entry
        if bench_entry.get("intelligence_index"):
            enrichment["ext_reasoning"] = _normalize_score(bench_entry["intelligence_index"])
        coding_score = bench_entry.get("coding_index") or bench_entry.get("humaneval") or bench_entry.get("swe_bench")
        if coding_score:
            enrichment["ext_coding"] = _normalize_score(coding_score)

    if not enrichment and not raw:
        return None

    enrichment["raw_benchmark_data"] = raw
    return enrichment


def _parse_price(value: Any) -> float | None:
    """Parse a price value to float (assumed per-million tokens)."""
    if value is None:
        return None
    try:
        return float(str(value).replace("$", "").strip())
    except (ValueError, TypeError):
        return None


def _normalize_score(value: Any, scale: float = 100.0) -> int:
    """Normalize a benchmark score to 0-100 integer scale."""
    try:
        score = float(value)
        if score <= 1.0:
            # Likely a 0-1 ratio
            return round(score * 100)
        if score <= scale:
            return round(score)
        return round((score / scale) * 100)
    except (ValueError, TypeError):
        return 0


async def enrich_model(
    db: AsyncSession,
    model_id: str,
    models_dev_data: list[dict[str, Any]],
    benchmark_data: list[dict[str, Any]],
) -> ModelEnrichment | None:
    """Enrich a single model and upsert to DB.

    Returns:
        The created/updated ModelEnrichment, or None if no external data matched.
    """
    matched = _match_model(model_id, models_dev_data, benchmark_data)
    if not matched:
        return None

    # Upsert
    result = await db.execute(
        select(ModelEnrichment).where(ModelEnrichment.model_id == model_id)
    )
    enrichment = result.scalar_one_or_none()

    now = datetime.now(UTC)
    if enrichment:
        enrichment.ext_coding = matched.get("ext_coding", enrichment.ext_coding)
        enrichment.ext_reasoning = matched.get("ext_reasoning", enrichment.ext_reasoning)
        enrichment.ext_speed_tier = matched.get("ext_speed_tier", enrichment.ext_speed_tier)
        enrichment.ext_input_per_m = matched.get("ext_input_per_m", enrichment.ext_input_per_m)
        enrichment.ext_output_per_m = matched.get("ext_output_per_m", enrichment.ext_output_per_m)
        enrichment.raw_benchmark_data = matched.get("raw_benchmark_data", enrichment.raw_benchmark_data)
        enrichment.synced_at = now
    else:
        enrichment = ModelEnrichment(
            model_id=model_id,
            ext_coding=matched.get("ext_coding"),
            ext_reasoning=matched.get("ext_reasoning"),
            ext_speed_tier=matched.get("ext_speed_tier"),
            ext_input_per_m=matched.get("ext_input_per_m"),
            ext_output_per_m=matched.get("ext_output_per_m"),
            raw_benchmark_data=matched.get("raw_benchmark_data"),
            source="models.dev+benchmarks",
            synced_at=now,
        )
        db.add(enrichment)

    return enrichment


async def sync_all(db: AsyncSession) -> dict[str, Any]:
    """Sync all catalog models with external data sources.

    Fetches from both sources, matches against MODEL_CATALOG, and upserts.

    Returns:
        Summary dict with counts.
    """
    models_dev_data: list[dict[str, Any]] = []
    benchmark_data: list[dict[str, Any]] = []

    # Fetch external data (best-effort — either source failing is non-fatal)
    try:
        models_dev_data = await fetch_models_dev()
        logger.info("Fetched %d entries from models.dev", len(models_dev_data))
    except Exception as e:
        logger.warning("Failed to fetch models.dev data: %s", e)

    try:
        benchmark_data = await fetch_benchmarks()
        logger.info("Fetched %d entries from benchmarks", len(benchmark_data))
    except Exception as e:
        logger.warning("Failed to fetch benchmark data: %s", e)

    if not models_dev_data and not benchmark_data:
        return {"status": "no_data", "enriched": 0, "total": len(MODEL_CATALOG)}

    enriched_count = 0
    for entry in MODEL_CATALOG:
        result = await enrich_model(db, entry.id, models_dev_data, benchmark_data)
        if result:
            enriched_count += 1

    await db.commit()

    logger.info("Model enrichment sync complete: %d/%d enriched", enriched_count, len(MODEL_CATALOG))
    return {
        "status": "success",
        "enriched": enriched_count,
        "total": len(MODEL_CATALOG),
        "sources": {
            "models_dev": len(models_dev_data),
            "benchmarks": len(benchmark_data),
        },
        "synced_at": datetime.now(UTC).isoformat(),
    }


async def get_all_enrichments(db: AsyncSession) -> dict[str, ModelEnrichment]:
    """Get all enrichments keyed by model_id.

    Returns:
        Dict mapping model_id → ModelEnrichment.
    """
    result = await db.execute(select(ModelEnrichment))
    return {e.model_id: e for e in result.scalars().all()}
