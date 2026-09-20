"""API interaction for agent management."""

from __future__ import annotations

from typing import Any

from ._api_paths import AGENTS_BASE_PATH, AGENTS_PREVIEW_PATH, MODELS_BASE_PATH
from .memory_api import agent_hub_request


def agents_api(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    """Make an Agent Hub agent-management request."""
    return agent_hub_request(method, f"{AGENTS_BASE_PATH}{path}", tool_name="st agents", **kwargs)


def agent_preview_api(slug: str, **kwargs: Any) -> dict[str, Any]:
    """Fetch runtime preview for an agent."""
    params = {
        key: value
        for key, value in kwargs.items()
        if value is not None
    }
    return agent_hub_request(
        "GET",
        AGENTS_PREVIEW_PATH.format(slug=slug),
        tool_name="st agents",
        params=params,
    )


def models_api() -> dict[str, Any]:
    """Fetch Agent Hub model catalog metadata for assignment scoring."""
    return agent_hub_request("GET", MODELS_BASE_PATH, tool_name="st agents")
