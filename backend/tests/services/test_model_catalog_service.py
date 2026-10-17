"""Tests for the DB-backed model catalog: seed only an empty DB, runtime snapshot, writes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.constants.catalog import (
    MODEL_ALIASES,
    MODEL_CATALOG,
    MODEL_CATALOG_BY_ID,
    replace_runtime_model_catalog,
)
from app.models.model_catalog import ModelAlias, ModelCatalogEntry
from app.services.model_catalog_service import (
    load_seed_catalog,
    row_to_model_entry,
    seed_model_catalog,
)


def _seed_row(model_id: str) -> dict:
    return next(row for row in load_seed_catalog()["models"] if row["id"] == model_id)


def test_row_to_model_entry_preserves_catalog_fields() -> None:
    seed = _seed_row("codex/gpt-6.1-sol")
    entry = row_to_model_entry(ModelCatalogEntry(**seed))

    assert entry.id == seed["id"]
    assert entry.provider == "codex"
    assert entry.alias == seed["alias"]
    assert entry.cost.input_per_m == seed["cost_input_per_m"]
    assert entry.cost.subscription_rates == {"credits_per_m": {"input": 50.0, "cached_input": 2.5, "output": 250.0}}
    assert entry.capabilities.supports_tool_execution is True
    assert entry.capabilities.max_output_tokens == seed["max_output_tokens"]


def test_seed_file_covers_every_catalog_column_and_alias_target() -> None:
    seed = load_seed_catalog()
    columns = {c.name for c in ModelCatalogEntry.__table__.columns} - {"created_at", "updated_at"}
    assert all(set(row) == columns for row in seed["models"])
    ids = {row["id"] for row in seed["models"]}
    assert all(alias["model_id"] in ids for alias in seed["aliases"])


@pytest.mark.asyncio
async def test_seed_fills_only_an_empty_catalog() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar.return_value = 0
    inserted = await seed_model_catalog(db)

    added = [call.args[0] for call in db.add.call_args_list]
    seed = load_seed_catalog()
    assert inserted == len(seed["models"]) + len(seed["aliases"])
    assert sum(isinstance(row, ModelCatalogEntry) for row in added) == len(seed["models"])
    assert sum(isinstance(row, ModelAlias) for row in added) == len(seed["aliases"])
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_seed_never_touches_a_populated_catalog() -> None:
    # A model retired or deleted in the DB must not come back on the next start.
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar.return_value = 3
    assert await seed_model_catalog(db) == 0
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


def test_replace_runtime_model_catalog_preserves_imported_containers() -> None:
    original_catalog_id = id(MODEL_CATALOG)
    original_by_id_id = id(MODEL_CATALOG_BY_ID)
    original_aliases_id = id(MODEL_ALIASES)
    original_entries = list(MODEL_CATALOG)
    original_aliases = dict(MODEL_ALIASES)
    replacement = [entry for entry in original_entries if entry.id == "codex/gpt-6.1-sol"]

    try:
        replace_runtime_model_catalog(replacement, {"codex": "codex/gpt-6.1-sol"})

        assert id(MODEL_CATALOG) == original_catalog_id
        assert id(MODEL_CATALOG_BY_ID) == original_by_id_id
        assert id(MODEL_ALIASES) == original_aliases_id
        assert list(MODEL_CATALOG_BY_ID) == ["codex/gpt-6.1-sol"]
        assert MODEL_ALIASES["codex"] == "codex/gpt-6.1-sol"
    finally:
        replace_runtime_model_catalog(original_entries, original_aliases)
