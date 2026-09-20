"""API interaction for prompt management."""

from __future__ import annotations

from typing import Any

from ._api_paths import PROMPTS_BASE_PATH
from .memory_api import agent_hub_request


def prompt_api(method: str, path: str, *, tool_name: str = "st prompt", **kwargs: Any) -> dict[str, Any]:
    """Make API request to prompt endpoints."""
    return agent_hub_request(method, f"{PROMPTS_BASE_PATH}{path}", tool_name=tool_name, **kwargs)
