"""Helper functions for completion API."""

from __future__ import annotations

import json
import logging
from typing import Any

import jsonschema

from app.adapters.base import Message
from app.constants import MODEL_ALIASES, MODEL_CATALOG
from app.constants.models import PROVIDER_NAMES

logger = logging.getLogger(__name__)

# Derive recognized @mention prefixes from PROVIDER_NAMES (single source of truth).
# Both bare provider and provider-prefixed forms.
_MENTION_PREFIXES: tuple[str, ...] = tuple(
    prefix for p in PROVIDER_NAMES for prefix in (p, f"{p}/")
)
def _exact_model_ids() -> dict[str, str]:
    return {entry.id.lower(): entry.id for entry in MODEL_CATALOG}


def validate_json_response(content: str, schema: dict[str, Any]) -> tuple[bool, str | None]:
    """Validate JSON response against a JSON Schema.

    Returns (is_valid, error_message). If valid, error_message is None.
    """
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"
    try:
        jsonschema.validate(instance=parsed, schema=schema)
        return True, None
    except jsonschema.ValidationError as e:
        return False, f"Schema validation failed: {e.message}"


# Keywords that suggest complex reasoning where thinking helps
# Inspired by Claude Code UX: Tab toggle, "ultrathink" trigger, sticky state
_THINKING_TRIGGERS = [
    "ultrathink",
    "think hard",
    "think carefully",
    "think step by step",
    "analyze",
    "evaluate",
    "compare",
    "explain why",
    "reason",
    "think through",
    "consider carefully",
    "debug",
    "review code",
    "find the bug",
    "what's wrong",
    "refactor",
    "multi-step",
    "complex",
    "edge cases",
]


def extract_text_content(content: str | list[dict[str, Any]]) -> str:
    """Extract text content from message content (string or content blocks)."""
    if isinstance(content, str):
        return content
    texts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            texts.append(block.get("text", ""))
        elif isinstance(block, str):
            texts.append(block)
    return " ".join(texts)


def parse_mention(content: str | list[dict[str, Any]]) -> tuple[str | None, str]:
    """Extract @model mention from message content.

    Supports aliases (@sonnet, @opus, @flash, etc.) and provider-prefixed models
    Provider-prefixed mentions are
    derived dynamically from PROVIDER_NAMES — adding a provider there auto-enables
    @mention support with zero changes here.

    Returns (resolved_model, cleaned_content) where resolved_model is None if no mention.
    """
    import re

    text = extract_text_content(content) if isinstance(content, list) else content
    match = re.search(r"@([\w/][\w./:-]*)", text, re.IGNORECASE)
    if not match:
        return None, text

    mention = match.group(1).lower().rstrip(".")
    resolved_model = MODEL_ALIASES.get(mention)
    if not resolved_model:
        resolved_model = _exact_model_ids().get(mention)
    if not resolved_model and "/" in mention and any(mention.startswith(p) for p in _MENTION_PREFIXES):
        resolved_model = mention

    if not resolved_model:
        return None, text

    cleaned = re.sub(r"@[\w/][\w./:-]*\s*", "", text, count=1).strip()
    return resolved_model, cleaned


def _has_thinking_trigger(text: str) -> bool:
    """Return True if text contains any thinking trigger keyword or numbered steps."""
    lower = text.lower()
    if any(trigger in lower for trigger in _THINKING_TRIGGERS):
        return True
    return any(f"{i}." in text for i in range(1, 10))


def should_enable_thinking(messages: list[Message]) -> bool:
    """Detect if request would benefit from extended thinking.

    Triggers on explicit thinking keywords, complex reasoning indicators,
    multi-step instructions (numbered lists), or code review/analysis requests.
    """
    for msg in reversed(messages):
        if msg.role == "user":
            return _has_thinking_trigger(extract_text_content(msg.content))
    return False


def normalize_content_for_storage(content: str | list[Any]) -> str:
    """Normalize message content for database storage.

    Multi-modal content (list of text/image blocks) is serialized to JSON.
    """
    if isinstance(content, list):
        return json.dumps(content)
    return content


def is_error_response(content: str) -> bool:
    """Detect error responses that should not be cached."""
    error_indicators = [
        "Usage Policy",
        "violate",
        "unable to respond to this request",
        "rate limit",
        "authentication failed",
    ]
    content_lower = content.lower()
    return any(ind.lower() in content_lower for ind in error_indicators)
