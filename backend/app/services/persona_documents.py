"""Shared helpers for persona documents and structured profile rendering."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

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

_LEGACY_SECTION_TO_FIELD: dict[str, str] = {
    "identity": "user_identity",
    "work context": "work_context",
    "communication style": "communication_style",
    "autonomy level": "autonomy_level",
    "notification preferences": "notification_preferences",
    "working schedule": "working_schedule",
    "priorities and values": "priorities_values",
    "tools and integration": "tools_and_integrations",
    "tools and integrations": "tools_and_integrations",
    "boundaries and escalation": "boundaries_and_escalation",
}
_LEGACY_SECTION_HEADER_RE = re.compile(r"^##\s+(.+?)\s*$")
_LEGACY_ROOT_HEADER_RE = re.compile(r"^#\s+User Profile:\s*.+$")
_TIMEZONE_LINE_RE = re.compile(r"(?im)^\s*[-*]?\s*Timezone:\s*(.+?)\s*$")
_TIMEZONE_ALIASES = {
    "est": "America/New_York",
    "edt": "America/New_York",
    "et": "America/New_York",
    "cst": "America/Chicago",
    "cdt": "America/Chicago",
    "ct": "America/Chicago",
    "mst": "America/Denver",
    "mdt": "America/Denver",
    "mt": "America/Denver",
    "pst": "America/Los_Angeles",
    "pdt": "America/Los_Angeles",
    "pt": "America/Los_Angeles",
}


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


def _canonicalize_legacy_heading(heading: str) -> str:
    return " ".join(
        heading.strip().lower().replace("&", "and").replace("/", " ").split()
    )


def _trim_block_lines(lines: list[str]) -> list[str]:
    trimmed = [line.rstrip() for line in lines]
    while trimmed and not trimmed[0].strip():
        trimmed.pop(0)
    while trimmed and not trimmed[-1].strip():
        trimmed.pop()
    return trimmed


def _normalize_legacy_section_text(lines: list[str]) -> str | None:
    trimmed = _trim_block_lines(lines)
    if not trimmed:
        return None
    return "\n".join(trimmed).strip() or None


def _format_legacy_section(heading: str, body: str | None) -> str:
    if body:
        return f"## {heading}\n{body}"
    return f"## {heading}"


def _normalize_legacy_timezone(raw_value: str) -> str | None:
    candidate = raw_value.strip()
    if not candidate:
        return None
    if "/" in candidate:
        return candidate
    return _TIMEZONE_ALIASES.get(candidate.lower())


def _remove_labeled_line(text: str, label: str) -> str | None:
    pattern = re.compile(rf"(?im)^\s*[-*]?\s*{re.escape(label)}:\s*.+?\s*$")
    lines = [line for line in text.splitlines() if not pattern.match(line)]
    normalized = _normalize_legacy_section_text(lines)
    return normalized


def split_legacy_user_context(
    text: str | None,
) -> tuple[dict[str, str] | None, str | None]:
    """Split legacy markdown user-context content into profile fields plus residual notes."""
    raw_text = (text or "").strip()
    if not raw_text:
        return None, None

    preamble: list[str] = []
    structured_sections: list[tuple[str, list[str]]] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    def _flush_current() -> None:
        nonlocal current_heading, current_lines
        if current_heading is not None:
            structured_sections.append((current_heading, current_lines))
            current_heading = None
            current_lines = []

    for raw_line in raw_text.splitlines():
        line = raw_line.rstrip()
        header_match = _LEGACY_SECTION_HEADER_RE.match(line.strip())
        if header_match:
            _flush_current()
            current_heading = header_match.group(1).strip()
            continue
        if current_heading is None:
            if line.strip() and not _LEGACY_ROOT_HEADER_RE.match(line.strip()):
                preamble.append(line)
            continue
        current_lines.append(line)
    _flush_current()

    extracted_profile: dict[str, str] = {}
    note_chunks: list[str] = []

    preamble_text = _normalize_legacy_section_text(preamble)
    if preamble_text:
        note_chunks.append(preamble_text)

    for heading, lines in structured_sections:
        body = _normalize_legacy_section_text(lines)
        field_key = _LEGACY_SECTION_TO_FIELD.get(_canonicalize_legacy_heading(heading))
        if field_key:
            if body:
                extracted_profile[field_key] = body
            continue
        note_chunks.append(_format_legacy_section(heading, body))

    normalized_profile = normalize_user_profile(extracted_profile)
    if not normalized_profile:
        return None, raw_text

    timezone_value: str | None = None
    for key in ("notification_preferences", "working_schedule"):
        source = normalized_profile.get(key)
        if not source:
            continue
        match = _TIMEZONE_LINE_RE.search(source)
        if not match:
            continue
        if timezone_value is None:
            timezone_value = _normalize_legacy_timezone(match.group(1))
            if timezone_value:
                normalized_profile["timezone"] = timezone_value
        cleaned = _remove_labeled_line(source, "Timezone")
        if cleaned:
            normalized_profile[key] = cleaned
        else:
            normalized_profile.pop(key, None)

    notes = "\n\n".join(chunk for chunk in note_chunks if chunk).strip() or None
    return normalized_profile, notes


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
    "get_user_profile_timezone",
    "normalize_user_profile",
    "render_user_profile",
    "split_legacy_user_context",
    "validate_text_document_update",
]
