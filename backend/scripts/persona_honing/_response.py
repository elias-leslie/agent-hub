"""Persona honing response parsing."""
from __future__ import annotations

import json
from typing import Any

from scripts.persona_benchmark_scoring import (
    _load_first_json_object,
    _strip_leading_narration_tags,
    strip_markdown_fences,
)

_HONING_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "changes_applied": {"type": "array", "items": {"type": "string"}},
        "next_focus": {"type": "array", "items": {"type": "string"}},
        "durable_learning_saved": {"type": "boolean"},
    },
    "required": ["summary", "changes_applied", "next_focus", "durable_learning_saved"],
}

_DECISION_REVIEW_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "decision": {"type": "string", "enum": ["promote", "hold", "rollback"]},
        "reason": {"type": "string"},
    },
    "required": ["decision", "reason"],
}


def parse_improvement_content(content: str) -> dict[str, Any] | None:
    cleaned = strip_markdown_fences(_strip_leading_narration_tags(content))
    try:
        parsed = _load_first_json_object(cleaned)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_decision_review_content(content: str) -> dict[str, Any] | None:
    cleaned = strip_markdown_fences(_strip_leading_narration_tags(content))
    try:
        parsed = _load_first_json_object(cleaned)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    decision = parsed.get("decision")
    reason = parsed.get("reason")
    if decision not in {"promote", "hold", "rollback"}:
        return None
    if not isinstance(reason, str) or not reason.strip():
        return None
    return {
        "decision": decision,
        "reason": reason.strip(),
    }


__all__ = [
    "_DECISION_REVIEW_RESPONSE_SCHEMA",
    "_HONING_RESPONSE_SCHEMA",
    "parse_decision_review_content",
    "parse_improvement_content",
]
