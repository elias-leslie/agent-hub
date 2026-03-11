"""Shared helpers for persona documents and structured profile rendering."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.models.persona import Persona

SHRINKAGE_MIN_LEN = 200
SHRINKAGE_RATIO = 0.5

USER_PROFILE_FIELDS: tuple[tuple[str, str], ...] = (
    ("user_identity", "User Identity"),
    ("work_context", "Work Context"),
    ("communication_style", "Communication Style"),
    ("autonomy_level", "Autonomy Level"),
    ("notification_preferences", "Notification Preferences"),
    ("timezone", "Timezone"),
    ("working_schedule", "Working Schedule"),
    ("priorities_values", "Priorities and Values"),
    ("tools_and_integrations", "Tools and Integrations"),
    ("boundaries_and_escalation", "Boundaries and Escalation"),
)


class PersonaDocumentShrinkageError(ValueError):
    """Raised when a document update looks like accidental data loss."""


def validate_text_document_update(old_text: str, new_text: str, *, field_label: str) -> tuple[str, str]:
    """Return stripped texts or raise when the update looks like accidental shrinkage."""
    old_value = old_text or ""
    new_value = new_text.strip()
    if len(old_value) > SHRINKAGE_MIN_LEN and len(new_value) < (len(old_value) * SHRINKAGE_RATIO):
        raise PersonaDocumentShrinkageError(
            f"REJECTED: New {field_label} ({len(new_value)} chars) is dramatically shorter "
            f"than existing ({len(old_value)} chars). This looks like accidental data loss."
        )
    return old_value, new_value


def apply_persona_text_update(persona: Persona, field: str, new_text: str, *, field_label: str | None = None) -> tuple[int, int]:
    """Update one persona text field with shrinkage protection and backup handling."""
    old_text, new_value = validate_text_document_update(
        getattr(persona, field) or "",
        new_text,
        field_label=field_label or field,
    )
    backup_field = f"{field}_previous"
    if hasattr(persona, backup_field):
        setattr(persona, backup_field, old_text)
    setattr(persona, field, new_value)
    return len(old_text), len(new_value)


def normalize_user_profile(value: Mapping[str, Any] | None) -> dict[str, str] | None:
    """Return a compact persona user_profile dict with known non-empty fields only."""
    if not value:
        return None
    normalized: dict[str, str] = {}
    for key, _label in USER_PROFILE_FIELDS:
        raw_value = value.get(key)
        if isinstance(raw_value, str):
            stripped = raw_value.strip()
            if stripped:
                normalized[key] = stripped
    return normalized or None


def render_user_profile(value: Mapping[str, Any] | None) -> str | None:
    """Render user_profile into a compact bullet list for prompt injection."""
    normalized = normalize_user_profile(value)
    if not normalized:
        return None
    return "\n".join(
        f"- {label}: {normalized[key]}"
        for key, label in USER_PROFILE_FIELDS
        if key in normalized
    )


def get_user_profile_timezone(value: Mapping[str, Any] | None) -> str | None:
    """Return the structured profile timezone when set."""
    normalized = normalize_user_profile(value)
    if not normalized:
        return None
    return normalized.get("timezone")


__all__ = [
    "SHRINKAGE_MIN_LEN",
    "SHRINKAGE_RATIO",
    "USER_PROFILE_FIELDS",
    "PersonaDocumentShrinkageError",
    "apply_persona_text_update",
    "get_user_profile_timezone",
    "normalize_user_profile",
    "render_user_profile",
    "validate_text_document_update",
]
