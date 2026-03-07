"""Helpers for deferred tool loading and tool catalog discovery."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from app.services.tools.base import Tool

TOOL_SEARCH_NAME = "tool_search"
TOOL_CATALOG_NAME = "tool_catalog"
VIRTUAL_TOOL_NAMES = frozenset({TOOL_SEARCH_NAME, TOOL_CATALOG_NAME})


def _tool_to_catalog_entry(tool: Tool | dict[str, Any]) -> dict[str, Any]:
    """Normalize Tool objects or dicts into catalog entries."""
    if isinstance(tool, Tool):
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
            "allowed_callers": list(tool.allowed_callers),
            "category": tool.category,
            "search_keywords": list(tool.search_keywords),
            "usage_examples": list(tool.usage_examples),
            "defer_loading": tool.defer_loading,
        }

    return {
        "name": tool["name"],
        "description": tool["description"],
        "input_schema": tool["input_schema"],
        "allowed_callers": list(tool.get("allowed_callers", ["direct"])),
        "category": tool.get("category"),
        "search_keywords": list(tool.get("search_keywords", [])),
        "usage_examples": list(tool.get("usage_examples", [])),
        "defer_loading": bool(tool.get("defer_loading", False)),
    }


def build_tool_catalog(tools: Iterable[Tool | dict[str, Any]]) -> list[dict[str, Any]]:
    """Return catalog entries for non-virtual tools."""
    return [
        _tool_to_catalog_entry(tool)
        for tool in tools
        if _tool_to_catalog_entry(tool)["name"] not in VIRTUAL_TOOL_NAMES
    ]


def _api_tool_from_catalog_entry(tool: dict[str, Any]) -> dict[str, Any]:
    """Return the provider-facing tool definition."""
    api_tool = {
        "name": tool["name"],
        "description": tool["description"],
        "input_schema": tool["input_schema"],
    }
    if tool.get("allowed_callers") != ["direct"]:
        api_tool["allowed_callers"] = tool["allowed_callers"]
    return api_tool


def build_tool_search_definition() -> dict[str, Any]:
    """Return the virtual tool used to search the deferred catalog."""
    return {
        "name": TOOL_SEARCH_NAME,
        "description": (
            "Search the full tool catalog by capability, workflow, or keyword. "
            "Use this before calling tool_catalog when you need a non-loaded tool."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Capability, workflow, or tool keyword to search for.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of matches to return.",
                    "default": 8,
                },
            },
            "required": ["query"],
        },
    }


def build_tool_catalog_definition() -> dict[str, Any]:
    """Return the virtual tool used to execute a discovered catalog tool."""
    return {
        "name": TOOL_CATALOG_NAME,
        "description": (
            "Execute a discovered tool by name. Use after tool_search when the tool "
            "you need is not directly loaded."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Name of the discovered tool to execute.",
                },
                "arguments": {
                    "type": "object",
                    "description": "Arguments for the discovered tool.",
                    "default": {},
                },
            },
            "required": ["tool_name"],
        },
    }


def build_deferred_toolset(
    tools: Iterable[Tool | dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (loaded_tools, catalog_tools) for a deferred-loading run."""
    catalog_tools = build_tool_catalog(tools)
    if not any(tool.get("defer_loading") for tool in catalog_tools):
        return ([_api_tool_from_catalog_entry(tool) for tool in catalog_tools], catalog_tools)

    loaded_tools = [
        _api_tool_from_catalog_entry(tool)
        for tool in catalog_tools
        if not tool.get("defer_loading")
    ]
    loaded_tools.extend(
        [build_tool_search_definition(), build_tool_catalog_definition()]
    )
    return loaded_tools, catalog_tools


def search_tool_catalog(
    catalog_tools: Iterable[dict[str, Any]],
    query: str,
    limit: int = 8,
) -> str:
    """Return a JSON search result payload for tool discovery."""
    query_terms = [term for term in query.lower().split() if term]

    def _score(tool: dict[str, Any]) -> tuple[int, str]:
        haystacks = [
            tool["name"].lower(),
            tool["description"].lower(),
            str(tool.get("category") or "").lower(),
            " ".join(tool.get("search_keywords", [])).lower(),
            " ".join(tool.get("usage_examples", [])).lower(),
        ]
        score = 0
        for term in query_terms:
            if term in haystacks[0]:
                score += 10
            if any(term in hay for hay in haystacks[1:]):
                score += 3
        return score, tool["name"]

    ranked = sorted(catalog_tools, key=_score, reverse=True)
    if query_terms:
        ranked = [tool for tool in ranked if _score(tool)[0] > 0]
    ranked = ranked[: max(1, min(limit, 20))]

    results = [
        {
            "name": tool["name"],
            "description": tool["description"],
            "category": tool.get("category"),
            "input_schema": tool["input_schema"],
            "usage_examples": tool.get("usage_examples", [])[:2],
            "search_keywords": tool.get("search_keywords", []),
            "deferred": bool(tool.get("defer_loading")),
            "invocation": (
                f"Use {TOOL_CATALOG_NAME} with tool_name='{tool['name']}' and "
                "arguments matching input_schema."
                if tool.get("defer_loading")
                else "This tool is already loaded and can be called directly."
            ),
        }
        for tool in ranked
    ]
    return json.dumps({"query": query, "results": results}, indent=2, sort_keys=True)
