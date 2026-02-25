"""Tool provisioning for completion API."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def provision_standard_tools(
    execute_tools: bool,
    tools: list[dict[str, Any]] | None,
    agent_slug: str | None = None,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """Auto-provision tools if execute_tools is enabled and no tools provided.

    Uses agent-specific tools from the registry when agent_slug is provided,
    falling back to standard tools (bash, read_file, write_file) otherwise.

    When project_id is provided, filters the tool list to only include tools
    allowed by the project's permission tier.

    Args:
        execute_tools: Whether tool execution is enabled
        tools: Existing tool definitions (if any)
        agent_slug: Agent slug for agent-specific tool lookup
        project_id: Project ID for tier-based tool filtering

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

    result = tools or []

    # Filter tools by project permission tier (soft enforcement at provisioning)
    if result and project_id:
        from app.services.project_permission_service import (
            _PERSONA_TOOLS,
            get_tools_for_tier,
        )

        # Synchronous tier lookup from cache — avoid async in provisioning.
        # Use a sync-safe approach: try Redis cache first, fall back to allowing all.
        try:
            import json

            import redis

            from app.config import settings

            r = redis.from_url(settings.agent_hub_redis_url, decode_responses=True)
            cached = r.get(f"agent-hub:project-perm:{project_id}")
            r.close()
            if cached:
                tier = json.loads(cached).get("tier")
                if tier:
                    # Persona tools are tier-exempt (checked at runtime by
                    # the permission hook), so always include them here.
                    allowed = get_tools_for_tier(tier) | _PERSONA_TOOLS
                    before = len(result)
                    result = [t for t in result if t.get("name") in allowed]
                    if len(result) < before:
                        logger.info(
                            "Filtered tools by tier '%s' for project '%s': %d -> %d",
                            tier, project_id, before, len(result),
                        )
        except Exception as e:
            logger.debug("Tool provisioning tier filter skipped: %s", e)

    return result
