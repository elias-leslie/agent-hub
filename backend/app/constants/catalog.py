"""Runtime model catalog with scores, costs, and capabilities.

Re-exports all public symbols from submodules so existing imports continue to work:
  from app.constants.catalog import MODEL_CATALOG, ModelEntry, resolve_model, ...

The catalog is the DB ``models`` and ``model_aliases`` tables, hydrated into this
process-local snapshot at startup (``refresh_runtime_model_catalog``). It is empty
until then; code refers to models by alias, never by a hardcoded id.
"""

from __future__ import annotations

from app.constants.catalog_types import (
    SCORE_WEIGHTS,
    ModelCapabilities,
    ModelCost,
    ModelEntry,
    ModelScores,
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
]

# ---------------------------------------------------------------------------
# Process-local snapshot of the DB catalog (empty until refreshed)
# ---------------------------------------------------------------------------

MODEL_CATALOG: list[ModelEntry] = []
MODEL_REGISTRY: list[dict[str, str]] = []
MODEL_CATALOG_BY_ID: dict[str, ModelEntry] = {}
MODEL_ALIASES: dict[str, str] = {}
# Catalogued but inactive rows: never routed, but their providers stay known so
# credentials can be stored before a model is re-enabled.
INACTIVE_MODEL_CATALOG_BY_ID: dict[str, ModelEntry] = {}


def _default_aliases(entries: list[ModelEntry]) -> dict[str, str]:
    return {entry.alias.lower(): entry.id for entry in entries if entry.alias}


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

