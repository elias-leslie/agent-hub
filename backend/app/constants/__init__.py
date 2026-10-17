"""Shared constants used across the application.

This module re-exports constants from submodules for backward compatibility.
"""
# ruff: noqa: F401

from __future__ import annotations

from app.constants.catalog import (
    MODEL_ALIASES,
    MODEL_CATALOG,
    MODEL_CATALOG_BY_ID,
    MODEL_REGISTRY,
    SCORE_WEIGHTS,
    ModelCapabilities,
    ModelCost,
    ModelEntry,
    ModelScores,
    get_model_capabilities,
    get_model_entry,
    resolve_model,
)
from app.constants.models import PROVIDER_NAMES
from app.constants.projects import VALID_PROJECT_IDS
from app.constants.subtask_types import (
    SUBTASK_TYPE_DESCRIPTIONS,
    SUBTASK_TYPES,
    format_subtask_types_markdown,
)

DEFAULT_RATE_LIMIT_TPM = 100_000

__all__ = [
    name
    for name in globals()
    if (
        name.isupper()
        or name in {
            "ModelCapabilities",
            "ModelCost",
            "ModelEntry",
            "ModelScores",
            "format_subtask_types_markdown",
            "get_model_capabilities",
            "get_model_entry",
            "resolve_model",
        }
    )
]
