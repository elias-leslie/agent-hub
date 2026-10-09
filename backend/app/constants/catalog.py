"""Runtime model catalog with scores, costs, and capabilities.

Re-exports all public symbols from submodules so existing imports continue to work:
  from app.constants.catalog import MODEL_CATALOG, ModelEntry, resolve_model, ...

Runtime data is hydrated from the DB ``models`` and ``model_aliases`` tables at
startup. ``catalog_entries.MODEL_CATALOG`` is retained as insert-only seed data.
"""

from __future__ import annotations

from app.constants.catalog_entries import MODEL_CATALOG as SEED_MODEL_CATALOG
from app.constants.catalog_types import (
    SCORE_WEIGHTS,
    ModelCapabilities,
    ModelCost,
    ModelEntry,
    ModelScores,
)
from app.constants.models import (
    CF_GLM_4_7_FLASH,
    CLAUDE_SONNET,
    CODEX_GPT_6_1_SOL,
    DEFAULT_GEMINI_MODEL,
    GEMINI_3_1_FLASH_LITE,
    LOCAL_GEMMA_4_12B,
    NVIDIA_NEMOTRON_3_SUPER,
    XAI_GROK_4_3,
)

__all__ = [
    "INACTIVE_MODEL_CATALOG_BY_ID",
    "MODEL_ALIASES",
    "MODEL_CATALOG",
    "MODEL_CATALOG_BY_ID",
    "MODEL_REGISTRY",
    "SCORE_WEIGHTS",
    "ModelCapabilities",
    "ModelCost",
    "ModelEntry",
    "ModelScores",
    "get_model_capabilities",
    "get_model_entry",
    "replace_runtime_model_catalog",
    "resolve_model",
    "seed_alias_overrides",
]

# ---------------------------------------------------------------------------
# Derived lookups — built once at import time from MODEL_CATALOG
# ---------------------------------------------------------------------------

MODEL_CATALOG: list[ModelEntry] = list(SEED_MODEL_CATALOG)
MODEL_REGISTRY: list[dict[str, str]] = []
MODEL_CATALOG_BY_ID: dict[str, ModelEntry] = {}
MODEL_ALIASES: dict[str, str] = {}
# Catalogued but inactive rows: never routed, but their providers stay known so
# credentials can be stored before a model is re-enabled.
INACTIVE_MODEL_CATALOG_BY_ID: dict[str, ModelEntry] = {}


def seed_alias_overrides() -> dict[str, str]:
    """Return seed/default aliases that are stored in DB on first boot."""
    return {
        # Bare provider names resolve to current default model for that provider.
        "claude": CLAUDE_SONNET,
        "cloudflare": CF_GLM_4_7_FLASH,
        "codex": CODEX_GPT_6_1_SOL,
        "flash": DEFAULT_GEMINI_MODEL,
        "gemini": GEMINI_3_1_FLASH_LITE,
        "local": LOCAL_GEMMA_4_12B,
        "nvidia": NVIDIA_NEMOTRON_3_SUPER,
        "xai": XAI_GROK_4_3,
    }


def _default_aliases(entries: list[ModelEntry]) -> dict[str, str]:
    valid_ids = {entry.id for entry in entries}
    aliases = {entry.alias.lower(): entry.id for entry in entries if entry.alias}
    aliases.update({
        alias.lower(): model_id
        for alias, model_id in seed_alias_overrides().items()
        if model_id in valid_ids
    })
    return aliases


def replace_runtime_model_catalog(
    entries: list[ModelEntry],
    aliases: dict[str, str] | None = None,
    inactive: list[ModelEntry] | None = None,
) -> None:
    """Replace process-local catalog snapshot while preserving imported containers."""
    INACTIVE_MODEL_CATALOG_BY_ID.clear()
    INACTIVE_MODEL_CATALOG_BY_ID.update({e.id: e for e in inactive or []})
    MODEL_CATALOG[:] = list(entries)
    MODEL_REGISTRY[:] = [
        {"id": e.id, "alias": e.alias, "name": e.name, "hint": e.hint, "provider": e.provider}
        for e in MODEL_CATALOG
    ]
    MODEL_CATALOG_BY_ID.clear()
    MODEL_CATALOG_BY_ID.update({e.id: e for e in MODEL_CATALOG})
    MODEL_ALIASES.clear()
    MODEL_ALIASES.update(aliases or _default_aliases(MODEL_CATALOG))


def resolve_model(alias: str) -> str:
    """Resolve model alias to canonical ID. Pass-through if not an alias."""
    return MODEL_ALIASES.get(alias.lower(), alias)


def get_model_entry(model: str) -> ModelEntry | None:
    """Return the catalog entry for a model id or alias."""
    return MODEL_CATALOG_BY_ID.get(resolve_model(model))


def get_model_capabilities(model: str) -> ModelCapabilities | None:
    """Return model capabilities from the catalog, if known."""
    entry = get_model_entry(model)
    return entry.capabilities if entry else None


replace_runtime_model_catalog(MODEL_CATALOG)
