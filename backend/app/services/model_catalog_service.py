"""DB-backed model catalog service."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.catalog_entries import MODEL_CATALOG as SEED_MODEL_CATALOG
from app.constants.catalog_types import (
    ModelCapabilities,
    ModelCost,
    ModelEntry,
    ModelPricingUnit,
    ModelScores,
)
from app.models.model_catalog import ModelAlias, ModelCatalogEntry

logger = logging.getLogger(__name__)


def _entry_values(entry: ModelEntry, sort_order: int) -> dict[str, Any]:
    return {
        "id": entry.id,
        "alias": entry.alias,
        "name": entry.name,
        "hint": entry.hint,
        "provider": entry.provider,
        "score_coding": entry.scores.coding,
        "score_reasoning": entry.scores.reasoning,
        "score_planning": entry.scores.planning,
        "score_tool_use": entry.scores.tool_use,
        "score_instruction": entry.scores.instruction,
        "score_design": entry.scores.design,
        "cost_input_per_m": entry.cost.input_per_m,
        "cost_output_per_m": entry.cost.output_per_m,
        "pricing_unit": entry.cost.pricing_unit,
        "unit_price": entry.cost.unit_price,
        "service_tiers": entry.cost.service_tiers,
        "cache_read_per_million": entry.cost.cache_read_per_million,
        "cache_write_per_million": entry.cost.cache_write_per_million,
        "context_window": entry.context_window,
        "speed_tier": entry.speed_tier,
        "can_generate_images": entry.capabilities.can_generate_images,
        "has_vision": entry.capabilities.has_vision,
        "can_edit_images": entry.capabilities.can_edit_images,
        "has_thinking": entry.capabilities.has_thinking,
        "supports_pdf": entry.capabilities.supports_pdf,
        "supports_audio": entry.capabilities.supports_audio,
        "supports_tool_execution": entry.capabilities.supports_tool_execution,
        "supports_verbosity": entry.capabilities.supports_verbosity,
        "supports_xhigh": entry.capabilities.supports_xhigh,
        "supports_session_cache": entry.capabilities.supports_session_cache,
        "max_output_tokens": entry.capabilities.max_output_tokens,
        "release_date": entry.release_date,
        "knowledge_cutoff": entry.knowledge_cutoff,
        "family": entry.family,
        "availability": entry.availability,
        "is_active": True,
        "sort_order": sort_order,
        "source": "seed",
    }


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
        ),
        release_date=row.release_date,
        knowledge_cutoff=row.knowledge_cutoff,
        family=row.family,
        availability=row.availability,
    )


def _seed_aliases(entries: Iterable[ModelEntry]) -> dict[str, tuple[str, str]]:
    """Build insert-only seed aliases as alias -> (model_id, alias_type)."""
    entries_by_id = {entry.id: entry for entry in entries}
    aliases: dict[str, tuple[str, str]] = {
        entry.alias.lower(): (entry.id, "canonical")
        for entry in entries_by_id.values()
        if entry.alias
    }

    from app.constants.catalog import seed_alias_overrides

    for alias, model_id in seed_alias_overrides().items():
        if model_id in entries_by_id:
            aliases[alias.lower()] = (model_id, "seed")
    return aliases


async def seed_model_catalog(db: AsyncSession) -> int:
    """Insert missing seed catalog rows and aliases; never overwrite DB values."""
    existing_models = set((await db.execute(select(ModelCatalogEntry.id))).scalars().all())
    inserted = 0
    for sort_order, entry in enumerate(SEED_MODEL_CATALOG, start=1):
        if entry.id in existing_models:
            continue
        db.add(ModelCatalogEntry(**_entry_values(entry, sort_order)))
        inserted += 1

    if inserted:
        await db.flush()

    existing_aliases = set((await db.execute(select(ModelAlias.alias))).scalars().all())
    for alias, (model_id, alias_type) in _seed_aliases(SEED_MODEL_CATALOG).items():
        if alias in existing_aliases:
            continue
        db.add(ModelAlias(alias=alias, model_id=model_id, alias_type=alias_type, source="seed"))
        inserted += 1

    if inserted:
        await db.commit()
    return inserted


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
    aliases = await get_model_aliases(db)
    from app.constants.catalog import replace_runtime_model_catalog

    replace_runtime_model_catalog(entries, aliases)
    logger.info("Loaded %d model catalog row(s) from DB", len(entries))
    return inserted
