"""Model enrichment service — fetches external benchmark/pricing data.

Enriches the static MODEL_CATALOG with data from:
- models.dev API (model metadata + pricing)
- arimxyer/models benchmarks.json (coding, reasoning, instruction)
- BFCL leaderboard (tool_use / function calling accuracy)
- LiveBench (planning / reasoning tasks, instruction following)

Stores enrichments in model_enrichments DB table as an overlay.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import MODEL_CATALOG
from app.models.model_enrichment import ModelEnrichment

if TYPE_CHECKING:
    from app.constants.catalog import ModelEntry

logger = logging.getLogger(__name__)

# External data sources
MODELS_DEV_URL = "https://models.dev/api.json"
BENCHMARKS_URL = "https://cdn.jsdelivr.net/gh/arimxyer/models@main/data/benchmarks.json"
BFCL_URL = "https://raw.githubusercontent.com/HuanzhiMao/BFCL-Result/main/2025-12-16/score/data_overall.csv"
LIVEBENCH_URL = "https://raw.githubusercontent.com/LiveBench/livebench.github.io/main/public/table_2026_01_08.csv"

# HTTP timeout
_HTTP_TIMEOUT = 30.0

# arimxyer benchmark index scale (scores go up to ~57)
_ARIMXYER_INDEX_SCALE = 57.0

# LiveBench task → category mapping
_LIVEBENCH_REASONING_TASKS = [
    "zebra_puzzle", "spatial", "connections", "consecutive_events",
    "logic_with_navigation", "theory_of_mind",
]
_LIVEBENCH_IF_TASKS = [
    "paraphrase", "story_generation", "typos", "summarize",
]


async def fetch_models_dev() -> list[dict[str, Any]]:
    """Fetch model catalog from models.dev API."""
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(MODELS_DEV_URL)
        resp.raise_for_status()
        data = resp.json()

    if isinstance(data, list):
        return data

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
    """Fetch benchmark data from arimxyer/models (jsdelivr CDN)."""
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(BENCHMARKS_URL)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return data.get("benchmarks", data.get("data", []))


async def fetch_bfcl() -> list[dict[str, Any]]:
    """Fetch BFCL (Berkeley Function Calling Leaderboard) data.

    Returns list of dicts with keys: Model, Overall Acc, Organization, etc.
    """
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(BFCL_URL)
        resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.text))
        return list(reader)


async def fetch_livebench() -> list[dict[str, Any]]:
    """Fetch LiveBench task-level scores.

    Returns list of dicts with keys: model, AMPS_Hard, code_completion, etc.
    """
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(LIVEBENCH_URL)
        resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.text))
        return list(reader)


def _bare_model_id(model_id: str) -> str:
    """Strip provider prefix from a catalog model_id.

    ``openai/gpt-5.2`` → ``gpt-5.2``, ``claude-sonnet-4-6`` → ``claude-sonnet-4-6``.
    """
    return model_id.rsplit("/", 1)[-1]


def _normalize_bfcl_name(name: str) -> str:
    """Normalize a BFCL model name to a bare model ID.

    "Claude-Opus-4-5-20251101 (FC)" → "claude-opus-4-5"
    "Gemini-3-Pro-Preview (Prompt)" → "gemini-3-pro-preview"
    "GLM-4.6 (FC thinking)" → "glm-4.6"
    """
    # Strip parenthetical suffix: (FC), (Prompt), (FC thinking), etc.
    name = re.sub(r"\s*\(.*?\)\s*$", "", name).strip()
    # Lowercase
    name = name.lower()
    # Strip date suffixes like -20251101
    name = re.sub(r"-\d{8,}$", "", name)
    return name


def _normalize_livebench_name(name: str) -> str:
    """Normalize a LiveBench model name to a bare model ID.

    "claude-opus-4-5-20251101-thinking-64k-high-effort" → "claude-opus-4-5"
    "claude-sonnet-4-5-20250929" → "claude-sonnet-4-5"
    "claude-haiku-4-5-20251001" → "claude-haiku-4-5"
    """
    name = name.strip().lower()
    # Strip date suffix and everything after it
    name = re.sub(r"-\d{8,}.*$", "", name)
    # Strip -base, -thinking-*, -high-effort, -low-effort, -medium-effort suffixes
    name = re.sub(r"-(base|thinking.*|high-effort|medium-effort|low-effort)$", "", name)
    return name


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

    stripped = bare_id.removesuffix("-preview")
    if stripped != bare_id:
        for entry in benchmark_data:
            slug = entry.get("slug", "")
            if not slug:
                continue
            if stripped == slug:
                return entry

    return None


def _find_in_bfcl(
    bare_id: str, family: str | None, bfcl_data: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Find a BFCL entry by normalized name match.

    Prefers (FC) entries over (Prompt) entries. Tries exact match on normalized
    name first, then family-prefix match (best scorer).
    """
    # Build normalized lookup: list of (normalized_name, original_model_name, row)
    candidates: list[tuple[str, str, dict[str, Any]]] = []
    for row in bfcl_data:
        model_name = row.get("Model", "").strip()
        if not model_name:
            continue
        norm = _normalize_bfcl_name(model_name)
        candidates.append((norm, model_name, row))

    # Exact match (stripped -preview too)
    bare_stripped = bare_id.removesuffix("-preview")
    exact_matches = [
        (orig, row) for norm, orig, row in candidates
        if norm in (bare_id, bare_stripped)
    ]
    if exact_matches:
        # Prefer (FC) over (Prompt)
        for orig, row in exact_matches:
            if "(FC)" in orig and "thinking" not in orig.lower():
                return row
        return exact_matches[0][1]

    # Family match — find best scorer in same family
    if family:
        family_matches = [
            (orig, row) for norm, orig, row in candidates
            if norm.startswith(family.replace("_", "-"))
        ]
        if family_matches:
            # Prefer (FC) entries, then highest Overall Acc
            fc_matches = [(o, r) for o, r in family_matches if "(FC)" in o and "thinking" not in o.lower()]
            pool = fc_matches or family_matches
            best = max(pool, key=lambda x: _parse_pct(x[1].get("Overall Acc", "0")))
            return best[1]

    return None


def _find_in_livebench(
    bare_id: str, family: str | None, livebench_data: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Find a LiveBench entry by normalized name match.

    Tries exact match, then family match (best overall scorer).
    """
    candidates: list[tuple[str, dict[str, Any]]] = []
    for row in livebench_data:
        model_name = row.get("model", "").strip()
        if not model_name:
            continue
        norm = _normalize_livebench_name(model_name)
        candidates.append((norm, row))

    bare_stripped = bare_id.removesuffix("-preview")
    exact = [row for norm, row in candidates if norm in (bare_id, bare_stripped)]
    if exact:
        # Pick the one with highest average score across all tasks
        return max(exact, key=lambda r: _livebench_avg(r, list(r.keys())))

    if family:
        family_matches = [
            row for norm, row in candidates
            if norm.startswith(family.replace("_", "-"))
        ]
        if family_matches:
            return max(family_matches, key=lambda r: _livebench_avg(r, list(r.keys())))

    return None


def _parse_pct(value: str) -> float:
    """Parse a percentage string like '77.47%' to float."""
    try:
        return float(str(value).replace("%", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _livebench_avg(row: dict[str, Any], tasks: list[str]) -> float:
    """Compute average score across given task columns in a LiveBench row."""
    values = []
    for task in tasks:
        if task == "model":
            continue
        try:
            v = float(row.get(task, 0))
            values.append(v)
        except (ValueError, TypeError):
            pass
    return sum(values) / len(values) if values else 0.0


def _livebench_category_avg(row: dict[str, Any], tasks: list[str]) -> float | None:
    """Compute average score for a specific category of LiveBench tasks."""
    values = []
    for task in tasks:
        try:
            v = float(row.get(task, 0))
            values.append(v)
        except (ValueError, TypeError):
            pass
    if not values:
        return None
    return sum(values) / len(values)


def _match_model(
    model_id: str,
    models_dev_data: list[dict[str, Any]],
    benchmark_data: list[dict[str, Any]],
    bfcl_data: list[dict[str, Any]],
    livebench_data: list[dict[str, Any]],
    catalog_entry: ModelEntry,
) -> dict[str, Any] | None:
    """Match a catalog model_id to all external data sources.

    Returns dict with enrichment fields, or None if no match found.
    """
    bare_id = _bare_model_id(model_id)
    family = catalog_entry.family
    enrichment: dict[str, Any] = {}
    raw: dict[str, Any] = {}

    # 1. models.dev — pricing + speed
    dev_entry = _find_in_models_dev(bare_id, models_dev_data)
    if dev_entry:
        raw["models_dev"] = dev_entry
        cost = dev_entry.get("cost", {})
        if cost:
            if "input" in cost:
                enrichment["ext_input_per_m"] = _parse_price(cost["input"])
            if "output" in cost:
                enrichment["ext_output_per_m"] = _parse_price(cost["output"])
        if dev_entry.get("output_tps"):
            tps = dev_entry["output_tps"]
            if tps >= 100:
                enrichment["ext_speed_tier"] = "fast"
            elif tps >= 40:
                enrichment["ext_speed_tier"] = "medium"
            else:
                enrichment["ext_speed_tier"] = "slow"

    # 2. arimxyer benchmarks — coding, reasoning, instruction (ifbench)
    bench_entry = _find_in_benchmarks(bare_id, benchmark_data)
    if bench_entry:
        raw["benchmarks"] = bench_entry
        if bench_entry.get("intelligence_index"):
            enrichment["ext_reasoning"] = _normalize_arimxyer_index(
                bench_entry["intelligence_index"]
            )
        coding_score = (
            bench_entry.get("coding_index")
            or bench_entry.get("humaneval")
            or bench_entry.get("swe_bench")
        )
        if coding_score:
            enrichment["ext_coding"] = _normalize_arimxyer_index(coding_score)

    # 3. BFCL — tool_use (function calling accuracy)
    bfcl_entry = _find_in_bfcl(bare_id, family, bfcl_data)
    if bfcl_entry:
        raw["bfcl"] = {
            "model": bfcl_entry.get("Model"),
            "overall_acc": bfcl_entry.get("Overall Acc"),
            "rank": bfcl_entry.get("Rank"),
        }
        overall_acc = _parse_pct(bfcl_entry.get("Overall Acc", "0"))
        if overall_acc > 0:
            enrichment["ext_tool_use"] = min(100, round(overall_acc))

    # 4. LiveBench — planning (reasoning tasks) + instruction (IF tasks)
    lb_entry = _find_in_livebench(bare_id, family, livebench_data)
    if lb_entry:
        raw["livebench"] = {"model": lb_entry.get("model")}

        reasoning_avg = _livebench_category_avg(lb_entry, _LIVEBENCH_REASONING_TASKS)
        if reasoning_avg is not None and reasoning_avg > 0:
            enrichment["ext_planning"] = min(100, round(reasoning_avg))
            raw["livebench"]["reasoning_avg"] = round(reasoning_avg, 1)

        if_avg = _livebench_category_avg(lb_entry, _LIVEBENCH_IF_TASKS)
        if if_avg is not None:
            raw["livebench"]["if_avg"] = round(if_avg, 1)

    # 5. Blend instruction: arimxyer ifbench + LiveBench IF avg
    arimxyer_if = None
    if bench_entry and bench_entry.get("ifbench"):
        try:
            v = float(bench_entry["ifbench"])
            # ifbench is 0-1 scale
            arimxyer_if = min(100, round(v * 100)) if v <= 1.0 else min(100, round(v))
        except (ValueError, TypeError):
            pass

    lb_if = None
    if lb_entry:
        lb_if_avg = _livebench_category_avg(lb_entry, _LIVEBENCH_IF_TASKS)
        if lb_if_avg is not None and lb_if_avg > 0:
            lb_if = min(100, round(lb_if_avg))

    if arimxyer_if is not None and lb_if is not None:
        enrichment["ext_instruction"] = round((arimxyer_if + lb_if) / 2)
    elif arimxyer_if is not None:
        enrichment["ext_instruction"] = arimxyer_if
    elif lb_if is not None:
        enrichment["ext_instruction"] = lb_if

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


def _normalize_arimxyer_index(value: Any) -> int:
    """Normalize an arimxyer benchmark index (0-57 scale) to 0-100."""
    try:
        score = float(value)
        return min(100, round(score / _ARIMXYER_INDEX_SCALE * 100))
    except (ValueError, TypeError):
        return 0


def _normalize_score(value: Any, scale: float = 100.0) -> int:
    """Normalize a benchmark score to 0-100 integer scale."""
    try:
        score = float(value)
        if score <= 1.0:
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
    fields = [
        "ext_coding", "ext_reasoning", "ext_tool_use", "ext_planning",
        "ext_instruction", "ext_speed_tier", "ext_input_per_m",
        "ext_output_per_m", "raw_benchmark_data",
    ]

    if enrichment:
        for f in fields:
            if f in matched:
                setattr(enrichment, f, matched[f])
        enrichment.synced_at = now
    else:
        enrichment = ModelEnrichment(
            model_id=model_id,
            **{f: matched.get(f) for f in fields},
            source="models.dev+benchmarks+bfcl+livebench",
            synced_at=now,
        )
        db.add(enrichment)

    return enrichment


async def sync_all(db: AsyncSession) -> dict[str, Any]:
    """Sync all catalog models with external data sources.

    Fetches from all 4 sources, matches against MODEL_CATALOG, and upserts.
    """
    models_dev_data: list[dict[str, Any]] = []
    benchmark_data: list[dict[str, Any]] = []
    bfcl_data: list[dict[str, Any]] = []
    livebench_data: list[dict[str, Any]] = []

    # Fetch external data (best-effort — any source failing is non-fatal)
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

    if not models_dev_data and not benchmark_data and not bfcl_data and not livebench_data:
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

    logger.info("Model enrichment sync complete: %d/%d enriched", enriched_count, len(MODEL_CATALOG))
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
