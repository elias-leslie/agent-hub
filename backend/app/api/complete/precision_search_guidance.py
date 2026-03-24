"""Soft guidance for Precision Code Search usage."""

from __future__ import annotations

import re
from typing import Any

from app.adapters._claude_constants import MCP_TOOL_PREFIX, build_mcp_tool_name

_CLAUDE_MCP_PREFIX = MCP_TOOL_PREFIX
_CLAUDE_BUILTIN_TOOL_NAMES = frozenset({"bash", "read_file", "write_file"})
_CLAUDE_TOOL_ALIAS_GUIDANCE_SENTINEL = (
    "For Claude tool runs, Agent Hub custom tools use MCP names"
)
_CLAUDE_ALIAS_EXAMPLE_PREFERENCE = (
    "research_web",
    "search_web",
    "fetch_web_page",
    "precision_code_search",
    "tool_search",
)

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


def _normalize_tool_name(name: str) -> str:
    if name.startswith("mcp__") and "__" in name[5:]:
        _, _, bare_name = name[5:].partition("__")
        if bare_name:
            return bare_name
    return name


def _has_precision_tool(tools: list[dict[str, Any]] | None) -> bool:
    return any(
        _normalize_tool_name(str(tool.get("name") or "")) == PRECISION_CODE_SEARCH_TOOL_NAME
        for tool in (tools or [])
    )


def _has_used_precision_search(messages: list[dict[str, Any]]) -> bool:
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and _normalize_tool_name(str(block.get("name") or ""))
                == PRECISION_CODE_SEARCH_TOOL_NAME
            ):
                return True
    return False


def _custom_claude_tool_names(tools: list[dict[str, Any]] | None) -> list[str]:
    names: list[str] = []
    for tool in tools or []:
        normalized_name = _normalize_tool_name(str(tool.get("name") or ""))
        if normalized_name and normalized_name not in _CLAUDE_BUILTIN_TOOL_NAMES:
            names.append(normalized_name)
    return names


def _prioritized_alias_examples(tool_names: list[str], limit: int = 4) -> list[str]:
    unique_names = list(dict.fromkeys(tool_names))
    ordered = [
        name for name in _CLAUDE_ALIAS_EXAMPLE_PREFERENCE if name in unique_names
    ]
    ordered.extend(sorted(name for name in unique_names if name not in ordered))
    return ordered[:limit]


def _build_claude_tool_alias_guidance(tools: list[dict[str, Any]] | None) -> str | None:
    custom_tool_names = _custom_claude_tool_names(tools)
    if not custom_tool_names:
        return None

    examples = ", ".join(
        f"`{name}` -> `{build_mcp_tool_name(name)}`"
        for name in _prioritized_alias_examples(custom_tool_names)
    )
    return (
        f"{_CLAUDE_TOOL_ALIAS_GUIDANCE_SENTINEL}: "
        "`mcp__agent-hub__<tool_name>`. When instructions mention a bare tool name, "
        "call the matching MCP tool directly instead of using ToolSearch to rediscover it."
        + (f" Examples: {examples}." if examples else "")
    )


def _has_claude_tool_alias_guidance(messages: list[dict[str, Any]]) -> bool:
    return any(
        message.get("role") == "system"
        and _CLAUDE_TOOL_ALIAS_GUIDANCE_SENTINEL in _extract_text(message.get("content"))
        for message in messages
    )


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


def maybe_inject_claude_tool_alias_guidance(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    *,
    provider: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Insert a one-time system reminder mapping bare tool names to Claude MCP names."""
    if provider != "claude" or _has_claude_tool_alias_guidance(messages):
        return messages, False

    guidance = _build_claude_tool_alias_guidance(tools)
    if not guidance:
        return messages, False

    guided_messages = list(messages)
    guided_messages.insert(0, {"role": "system", "content": guidance})
    return guided_messages, True


__all__ = [
    "PRECISION_CODE_SEARCH_REMINDER",
    "PRECISION_CODE_SEARCH_TOOL_NAME",
    "maybe_inject_claude_tool_alias_guidance",
    "maybe_inject_precision_search_guidance",
    "should_inject_precision_search_guidance",
]
