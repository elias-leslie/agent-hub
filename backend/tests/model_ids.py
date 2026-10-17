"""Model ids and the seed catalog for tests. The app itself only knows models from the DB catalog."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.constants.catalog import ModelEntry, replace_runtime_model_catalog
from app.services.model_catalog_service import load_seed_catalog, row_to_model_entry

CLAUDE_HAIKU = "claude-haiku-5-5"
CLAUDE_SONNET = "claude-sonnet-5-5"
CLAUDE_OPUS = "claude-opus-5-5"
CODEX_GPT_6_1_SOL = "codex/gpt-6.1-sol"
CODEX_GPT_6_SOL = "codex/gpt-6-sol"
CODEX_GPT_6_LUNA = "codex/gpt-6-luna"
GEMINI_2_5_FLASH = "gemini-2.5-flash"
GEMINI_3_5_FLASH = "gemini-3.5-flash"
# What the "flash" alias points at in the seed catalog.
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"


def _seed_rows() -> list[dict[str, Any]]:
    return sorted(load_seed_catalog()["models"], key=lambda row: (row.get("sort_order", 0), row["id"]))


def _entries(active: bool) -> list[ModelEntry]:
    return [
        row_to_model_entry(SimpleNamespace(**row))
        for row in _seed_rows()
        if bool(row.get("is_active", True)) is active
    ]


# The active seed catalog (what MODEL_CATALOG holds after a fresh install's refresh).
MODEL_CATALOG: list[ModelEntry] = _entries(active=True)


def hydrate_seed_catalog() -> None:
    """Load the exported seed catalog into the process the way startup loads the DB."""
    aliases = {row["alias"].lower(): row["model_id"] for row in load_seed_catalog()["aliases"]}
    replace_runtime_model_catalog(list(MODEL_CATALOG), aliases, _entries(active=False))
