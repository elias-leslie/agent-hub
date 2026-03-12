"""Soft guidance for Precision Code Search usage."""

from __future__ import annotations

import re
from typing import Any

PRECISION_CODE_SEARCH_TOOL_NAME = "precision_code_search"
PRECISION_CODE_SEARCH_REMINDER = (
    "Use precision_code_search first for symbol or implementation lookup "
    "(functions, classes, components, handlers, endpoints, schemas, "
    "tool definitions, registrations, and wiring). Start with the exact symbol "
    "or tool name when you have it, then refine if needed. The tool is symbol-first "
    "and already broadens to indexed text fallback when symbols miss. Only switch to "
    "raw rg/text search if its result is empty, stale, or irrelevant."
)

_WORKFLOW_META_TERMS = (
    "cleanup",
    "ownership",
    "owner",
    "status",
    "closeout",
    "citation",
    "citations",
    "coordination",
    "merge",
    "commit",
    "branch",
    "rebase",
    "release",
    "roadmap",
)
_CODE_NAV_TERMS = (
    "where is",
    "where are",
    "find ",
    "locate",
    "defined",
    "implemented",
    "implementation",
    "definition",
    "callsite",
    "call site",
    "usage",
    "references",
    "registered",
    "registration",
    "wired",
    "wiring",
    "tool path",
    "tooling path",
    "shared tool",
    "executor",
    "registry",
    "handler",
    "endpoint",
    "route",
    "schema",
    "function",
    "method",
    "class",
    "component",
    "service",
    "hook",
    "symbol",
)
_IDENTIFIER_PATTERN = re.compile(
    r"\b([a-z]+_[a-z0-9_]+|[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]+)+)\b"
)


def _extract_text(content: str | list[dict[str, Any]] | None) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(part for part in parts if part)


def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return _extract_text(message.get("content"))
    return ""


def _has_precision_tool(tools: list[dict[str, Any]] | None) -> bool:
    return any(tool.get("name") == PRECISION_CODE_SEARCH_TOOL_NAME for tool in (tools or []))


def _has_used_precision_search(messages: list[dict[str, Any]]) -> bool:
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and block.get("name") == PRECISION_CODE_SEARCH_TOOL_NAME
            ):
                return True
    return False


def _looks_like_workflow_meta(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in _WORKFLOW_META_TERMS)


def _looks_like_code_navigation(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in _CODE_NAV_TERMS) or bool(_IDENTIFIER_PATTERN.search(text))


def should_inject_precision_search_guidance(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
) -> bool:
    """Return True when a soft Precision Code Search reminder should fire."""
    if not _has_precision_tool(tools) or _has_used_precision_search(messages):
        return False

    latest_user_text = _latest_user_text(messages).strip()
    if not latest_user_text or _looks_like_workflow_meta(latest_user_text):
        return False

    return _looks_like_code_navigation(latest_user_text)


def maybe_inject_precision_search_guidance(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], bool]:
    """Insert a one-time system reminder when Precision Code Search should be used."""
    if not should_inject_precision_search_guidance(messages, tools):
        return messages, False

    guided_messages = list(messages)
    insert_at = 0
    while insert_at < len(guided_messages) and guided_messages[insert_at].get("role") == "system":
        insert_at += 1
    guided_messages.insert(
        insert_at,
        {
            "role": "system",
            "content": PRECISION_CODE_SEARCH_REMINDER,
        },
    )
    return guided_messages, True


__all__ = [
    "PRECISION_CODE_SEARCH_REMINDER",
    "PRECISION_CODE_SEARCH_TOOL_NAME",
    "maybe_inject_precision_search_guidance",
    "should_inject_precision_search_guidance",
]
