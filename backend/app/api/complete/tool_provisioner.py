"""Tool provisioning for completion API."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def provision_standard_tools(
    execute_tools: bool,
    tools: list[dict[str, Any]] | None,
    agent_slug: str | None = None,
) -> list[dict[str, Any]]:
    """Auto-provision tools if execute_tools is enabled and no tools provided.

    Uses agent-specific tools from the registry when agent_slug is provided,
    falling back to standard tools (bash, read_file, write_file) otherwise.

    Args:
        execute_tools: Whether tool execution is enabled
        tools: Existing tool definitions (if any)
        agent_slug: Agent slug for agent-specific tool lookup

    Returns:
        Tool definitions (either existing or auto-provisioned)
    """
    if execute_tools and not tools:
        # Try agent-specific tools first, fall back to standard tools
        if agent_slug:
            from app.services.tools.tool_definitions import get_agent_tools

            tools = get_agent_tools(agent_slug)

        if not tools:
            from app.services.tools.direct_executor import get_standard_tools

            tools = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in get_standard_tools()
            ]

        logger.info(f"Auto-provided {len(tools)} tools for execute_tools mode (agent={agent_slug})")

    return tools or []
