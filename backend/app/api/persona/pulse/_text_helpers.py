"""Low-level text matching and extraction helpers for pulse classification."""

from __future__ import annotations

import json
import re
from typing import Any

from app.api.persona.schemas import PersonaStreamEventPreview

from ._constants import (
    ALLOWED_COMMAND_PREFIXES,
    HUMAN_TEXT_KEYS,
    RAW_COMMAND_RULES,
)


def contains_term(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(contains_term(text, term) for term in terms)


def normalize_issue_key(value: str) -> str:
    normalized = value.lower()
    normalized = re.sub(r"task-[a-z0-9]+", "task-id", normalized)
    normalized = re.sub(r"\b[0-9]+\b", "#", normalized)
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    return normalized.strip("-")[:80]


def primary_value(values: set[str], order: tuple[str, ...]) -> str | None:
    for value in order:
        if value in values:
            return value
    return next(iter(values), None)


def first_matching_rule(command: str) -> tuple[str, str, str] | None:
    normalized = command.lower().strip()
    if normalized.startswith(ALLOWED_COMMAND_PREFIXES):
        return None
    for pattern, root_cause, title in RAW_COMMAND_RULES:
        if normalized.startswith(pattern):
            return pattern, root_cause, title
    return None


def is_prompt_like_text(text: str) -> bool:
    return (
        "# persona safety boundaries" in text
        or "<persona_context>" in text
        or "<heartbeat_instructions>" in text
        or (len(text) > 900 and text.count("\n") > 20)
    )


def parse_structured_preview(value: str | None) -> Any:
    if not value:
        return None
    stripped = value.strip()
    if not stripped.startswith("{") and not stripped.startswith("["):
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def first_human_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    if isinstance(value, dict):
        for key in HUMAN_TEXT_KEYS:
            candidate = first_human_text(value.get(key))
            if candidate:
                return candidate
        for candidate in value.values():
            resolved = first_human_text(candidate)
            if resolved:
                return resolved
        return None
    if isinstance(value, list):
        for item in value:
            resolved = first_human_text(item)
            if resolved:
                return resolved
        return None
    return str(value)


def human_preview_text(preview: PersonaStreamEventPreview) -> str | None:
    for raw_value in (
        preview.content_preview,
        preview.tool_output_preview,
        preview.tool_input_preview,
    ):
        if not raw_value:
            continue
        structured = parse_structured_preview(raw_value)
        candidate = first_human_text(structured if structured is not None else raw_value)
        if candidate:
            return candidate
    return None


def human_text_from_raw(raw_value: str | None) -> str | None:
    if not raw_value:
        return None
    structured = parse_structured_preview(raw_value)
    candidate = first_human_text(structured if structured is not None else raw_value)
    if not candidate:
        return None
    normalized = candidate.strip()
    return normalized or None


def preview_text(preview: PersonaStreamEventPreview) -> str:
    return " ".join(
        part
        for part in [
            preview.content_preview,
            preview.tool_input_preview,
            preview.tool_output_preview,
            preview.tool_name,
            preview.role,
            preview.event_type,
        ]
        if isinstance(part, str) and part
    ).lower()


def should_ignore_preview(preview: PersonaStreamEventPreview, text: str) -> bool:
    return preview.event_type in {"system_message", "memory_inject", "memory_cite"} or is_prompt_like_text(text)


def tool_output_flags(preview: PersonaStreamEventPreview) -> tuple[str | None, int | str | None, bool | None]:
    structured = parse_structured_preview(preview.tool_output_preview)
    if not isinstance(structured, dict):
        return None, None, None
    status = structured.get("status")
    exit_code = structured.get("exit_code")
    is_error = structured.get("is_error")
    return (
        str(status).lower() if status is not None else None,
        exit_code,
        is_error if isinstance(is_error, bool) else None,
    )


def preview_has_error(preview: PersonaStreamEventPreview, text: str) -> bool:
    if preview.event_type == "error":
        return True
    if contains_any(text, ("error", "failed", "failure", "traceback", "exception", "enoent", "non-zero exit", "exit code 1", "exit code 2", "command failed")):
        return True
    status, exit_code, is_error = tool_output_flags(preview)
    if status in {"error", "failed", "blocked"}:
        return True
    if exit_code not in (None, 0, "0"):
        return True
    return is_error is True


def preview_has_success(preview: PersonaStreamEventPreview, text: str) -> bool:
    if preview.event_type == "assistant_message" and "session interrupted" in text:
        return False
    if contains_any(text, ("passed", "completed", "succeeded", "verified", "published", "merged", "fixed", "resolved")):
        return True
    status, exit_code, _is_error = tool_output_flags(preview)
    if status in {"ok", "success", "completed", "passed"}:
        return True
    return exit_code in (0, "0")


def extract_command(preview: PersonaStreamEventPreview) -> str | None:
    tool_input = preview.tool_input_preview or ""
    for key in ("command", "cmd", "invocation"):
        match = re.search(rf'"{key}"\s*:\s*"([^"]+)"', tool_input)
        if match:
            return match.group(1).strip()
    if preview.tool_name and preview.event_type == "tool_use":
        return preview.tool_name.strip()
    return None
