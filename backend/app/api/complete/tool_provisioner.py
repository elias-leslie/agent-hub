"""Tool provisioning for completion API."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def provision_standard_tools(
    execute_tools: bool,
    tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Auto-provision standard tools if execute_tools is enabled and no tools provided.

    Args:
        execute_tools: Whether tool execution is enabled
        tools: Existing tool definitions (if any)

    Returns:
        Tool definitions (either existing or auto-provisioned)
    """
    if execute_tools and not tools:
        from app.services.tools.direct_executor import get_standard_tools

        tools = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in get_standard_tools()
        ]
        logger.info(f"Auto-provided {len(tools)} standard tools for execute_tools mode")

    return tools or []
