"""Tests for DB-backed model catalog helpers."""

from __future__ import annotations

from app.constants.catalog import (
    MODEL_ALIASES,
    MODEL_CATALOG,
    MODEL_CATALOG_BY_ID,
    replace_runtime_model_catalog,
)
from app.constants.catalog_entries import MODEL_CATALOG as SEED_MODEL_CATALOG
from app.models.model_catalog import ModelCatalogEntry
from app.services.model_catalog_service import _entry_values, row_to_model_entry


def test_row_to_model_entry_preserves_catalog_fields() -> None:
    seed = next(entry for entry in SEED_MODEL_CATALOG if entry.id == "codex/gpt-6.1-sol")
    row = ModelCatalogEntry(**_entry_values(seed, 1))

    entry = row_to_model_entry(row)

    assert entry.id == seed.id
    assert entry.provider == "codex"
    assert entry.alias == seed.alias
    assert entry.cost.input_per_m == seed.cost.input_per_m
    assert entry.capabilities.supports_tool_execution is True
    assert entry.capabilities.max_output_tokens == seed.capabilities.max_output_tokens


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
