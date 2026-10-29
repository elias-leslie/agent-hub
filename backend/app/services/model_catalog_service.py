"""DB-backed model catalog service."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.catalog_types import (
    ModelCapabilities,
    ModelCost,
    ModelEntry,
    ModelPricingUnit,
    ModelScores,
)
from app.models.model_catalog import ModelAlias, ModelCatalogEntry

logger = logging.getLogger(__name__)

SEED_CATALOG_FILE = Path(__file__).resolve().parents[2] / "scripts" / "seed_agents_data" / "model_catalog.json"


def row_to_model_entry(row: ModelCatalogEntry) -> ModelEntry:
    """Convert a DB row to the catalog domain object."""
    service_tiers = row.service_tiers if isinstance(row.service_tiers, dict) else {}
    return ModelEntry(
        id=row.id,
        alias=row.alias,
        name=row.name,
        hint=row.hint,
        provider=row.provider,
        scores=ModelScores(
            coding=row.score_coding,
            reasoning=row.score_reasoning,
            planning=row.score_planning,
            tool_use=row.score_tool_use,
            instruction=row.score_instruction,
            design=row.score_design,
        ),
        cost=ModelCost(
            input_per_m=row.cost_input_per_m,
            output_per_m=row.cost_output_per_m,
            pricing_unit=cast(ModelPricingUnit, row.pricing_unit),
            unit_price=row.unit_price,
            service_tiers=cast(dict[str, float], service_tiers),
            cache_read_per_million=row.cache_read_per_million,
            cache_write_per_million=row.cache_write_per_million,
            subscription_rates=getattr(row, "subscription_rates", None),
        ),
        context_window=row.context_window,
        speed_tier=row.speed_tier,
        capabilities=ModelCapabilities(
            can_generate_images=row.can_generate_images,
            has_vision=row.has_vision,
            can_edit_images=row.can_edit_images,
            has_thinking=row.has_thinking,
            supports_pdf=row.supports_pdf,
            supports_audio=row.supports_audio,
            supports_tool_execution=row.supports_tool_execution,
            supports_verbosity=row.supports_verbosity,
            supports_xhigh=row.supports_xhigh,
            supports_session_cache=row.supports_session_cache,
            max_output_tokens=row.max_output_tokens,
            supports_chat=getattr(row, "supports_chat", True),
            supports_typed_judgment=getattr(row, "supports_typed_judgment", False),
            max_state_question_tokens=getattr(row, "max_state_question_tokens", None),
            thinking_level_map=getattr(row, "thinking_level_map", None),
        ),
        upstream_id=getattr(row, "upstream_id", None),
        api=getattr(row, "api", None),
        access_programs=getattr(row, "access_programs", None),
        release_date=row.release_date,
        knowledge_cutoff=row.knowledge_cutoff,
        family=row.family,
        availability=row.availability,
    )


def load_seed_catalog(path: Path = SEED_CATALOG_FILE) -> dict[str, list[dict[str, Any]]]:
    """Read the exported catalog a fresh install starts from (scripts/export_seeds.py)."""
    data = json.loads(path.read_text())
    return {"models": list(data.get("models", [])), "aliases": list(data.get("aliases", []))}


async def seed_model_catalog(db: AsyncSession) -> int:
    """Seed an empty catalog from the exported file; never touch a populated one.

    The DB is the only catalog: rows edited, retired or deleted there stay that way.
    """
    if await db.scalar(select(func.count()).select_from(ModelCatalogEntry)):
        return 0
    seed = load_seed_catalog()
    for row in seed["models"]:
        db.add(ModelCatalogEntry(**row))
    await db.flush()
    known = {row["id"] for row in seed["models"]}
    aliases = [row for row in seed["aliases"] if row["model_id"] in known]
    for row in aliases:
        db.add(ModelAlias(**row))
    await db.commit()
    return len(seed["models"]) + len(aliases)


async def get_model_catalog_entries(db: AsyncSession, *, active_only: bool = True) -> list[ModelEntry]:
    """Load catalog entries from DB."""
    stmt = select(ModelCatalogEntry).order_by(ModelCatalogEntry.sort_order, ModelCatalogEntry.id)
    if active_only:
        stmt = stmt.where(ModelCatalogEntry.is_active == True)  # noqa: E712
    result = await db.execute(stmt)
    return [row_to_model_entry(row) for row in result.scalars().all()]


async def get_model_aliases(db: AsyncSession) -> dict[str, str]:
    """Load aliases from DB."""
    result = await db.execute(select(ModelAlias))
    return {row.alias.lower(): row.model_id for row in result.scalars().all()}


async def refresh_runtime_model_catalog(db: AsyncSession) -> int:
    """Hydrate process-local catalog snapshot from the DB-backed catalog."""
    inserted = await seed_model_catalog(db)
    entries = await get_model_catalog_entries(db)
    active_ids = {entry.id for entry in entries}
    inactive = [
        entry
        for entry in await get_model_catalog_entries(db, active_only=False)
        if entry.id not in active_ids
    ]
    aliases = await get_model_aliases(db)
    from app.constants.catalog import replace_runtime_model_catalog

    replace_runtime_model_catalog(entries, aliases, inactive)
    logger.info("Loaded %d model catalog row(s) from DB", len(entries))
    return inserted
