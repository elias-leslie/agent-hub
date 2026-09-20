"""Validation helpers for feedback commands."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

import typer
from st_sdk.output import output_error

from .feedback_helpers import VALID_SEVERITIES, VALID_SORTS, VALID_TYPES

MAX_SUGGESTIONS = 5
MAX_FALLBACK_COMPONENTS = 10
MAX_FEEDBACK_LIMIT = 200


def _component_map_module() -> ModuleType | None:
    try:
        return import_module("app.services.memory.scorecard_component_map")
    except Exception:
        return None


def _get_component_suggestions(bad_id: str) -> list[str]:
    """Get component ID suggestions for fuzzy matching."""
    module = _component_map_module()
    get_all_component_ids = getattr(module, "get_all_component_ids", None) if module else None
    if not callable(get_all_component_ids):
        return []

    all_ids = get_all_component_ids()
    prefix = bad_id.split(".")[0] + "."
    return [cid for cid in all_ids if cid.startswith(prefix)]


def validate_component_id(component_id: str) -> None:
    """Validate component ID, show suggestions on failure."""
    module = _component_map_module()
    is_valid_component_id = getattr(module, "is_valid_component_id", None) if module else None
    if not callable(is_valid_component_id):
        return  # Can't validate, let server handle it
    if is_valid_component_id(component_id):
        return

    suggestions = _get_component_suggestions(component_id)
    msg = f'Unknown component "{component_id}".'
    if suggestions:
        msg += f' Did you mean: {", ".join(suggestions[:MAX_SUGGESTIONS])}?'
    else:
        get_all_component_ids = getattr(module, "get_all_component_ids", None)
        if callable(get_all_component_ids):
            all_ids = get_all_component_ids()
            msg += f'\nValid components: {", ".join(all_ids[:MAX_FALLBACK_COMPONENTS])}...'
    output_error(msg)
    raise typer.Exit(1)


def validate_feedback_type(feedback_type: str) -> None:
    """Validate feedback type against VALID_TYPES."""
    if feedback_type not in VALID_TYPES:
        output_error(f'Invalid type "{feedback_type}". Valid types: {", ".join(VALID_TYPES)}')
        raise typer.Exit(1)


def validate_severity(severity: str | None) -> None:
    """Validate severity against VALID_SEVERITIES if provided."""
    if severity and severity not in VALID_SEVERITIES:
        output_error(f'Invalid severity "{severity}". Valid: {", ".join(VALID_SEVERITIES)}')
        raise typer.Exit(1)


def validate_sort(sort: str) -> None:
    """Validate feedback list/search sort values."""
    if sort in VALID_SORTS:
        return
    output_error(f'Invalid sort "{sort}". Valid sorts: {", ".join(VALID_SORTS)}')
    raise typer.Exit(1)


def validate_limit(limit: int) -> None:
    """Validate list/search limits against the feedback API cap."""
    if 1 <= limit <= MAX_FEEDBACK_LIMIT:
        return
    output_error(f"Limit must be between 1 and {MAX_FEEDBACK_LIMIT}.")
    raise typer.Exit(1)
