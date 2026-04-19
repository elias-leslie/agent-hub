"""Tool provisioning for completion API."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.services.tools.catalog import build_deferred_toolset, build_tool_catalog

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolProvisioningResult:
    """Provisioned tool surface plus the full execution catalog."""

    loaded_tools: list[dict[str, Any]]
    catalog_tools: list[dict[str, Any]]


def _resolve_tools(
    tools: list[dict[str, Any]] | None,
    agent_slug: str | None,
) -> list[dict[str, Any]]:
    """Resolve agent-specific tools when available, else fall back to core tools."""
    del tools

    if agent_slug:
        from app.services.tools.tool_definitions import get_agent_tool_specs

        agent_tool_specs = get_agent_tool_specs(agent_slug)
        if agent_tool_specs:
            return build_tool_catalog(agent_tool_specs)

    from app.services.tools.direct_executor import get_standard_tools

    return build_tool_catalog(get_standard_tools())


def _filter_tools_by_tier(
    result: list[dict[str, Any]],
    project_id: str,
    visible_tool_names: set[str] | frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Filter tools by project permission tier using Redis cache (best-effort)."""
    if visible_tool_names is not None:
        before = len(result)
        allowed = set(visible_tool_names)
        filtered = [t for t in result if t.get("name") in allowed]
        if len(filtered) < before:
            logger.info(
                "Filtered tools by explicit visible set for project '%s': %d -> %d",
                project_id,
                before,
                len(filtered),
            )
        return filtered

    from app.services.project_permission_service import (
        get_visible_tools_for_tier,
    )

    try:
        import json

        import redis

        from app.config import settings

        r = redis.from_url(settings.agent_hub_redis_url, decode_responses=True)
        cached = r.get(f"agent-hub:project-perm:{project_id}")
        r.close()

        if not cached:
            return result

        tier = json.loads(cached).get("tier")
        if not tier:
            return result

        allowed = get_visible_tools_for_tier(tier)
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


def provision_standard_tools(
    execute_tools: bool,
    tools: list[dict[str, Any]] | None,
    agent_slug: str | None = None,
    project_id: str | None = None,
    defer_tool_loading: bool = False,
    visible_tool_names: set[str] | frozenset[str] | None = None,
) -> ToolProvisioningResult:
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
        Provisioned loaded tools plus the full catalog
    """
    if execute_tools and not tools:
        tools = _resolve_tools(tools, agent_slug)
        logger.info(f"Auto-provided {len(tools)} tools for execute_tools mode (agent={agent_slug})")

    result = tools or []

    # Filter tools by project permission tier (soft enforcement at provisioning)
    if result and project_id:
        result = _filter_tools_by_tier(
            result,
            project_id,
            visible_tool_names=visible_tool_names,
        )

    catalog_tools = build_tool_catalog(result)
    if defer_tool_loading:
        loaded_tools, catalog_tools = build_deferred_toolset(catalog_tools)
    else:
        loaded_tools = [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["input_schema"],
                **(
                    {"allowed_callers": t["allowed_callers"]}
                    if t.get("allowed_callers") != ["direct"]
                    else {}
                ),
            }
            for t in catalog_tools
        ]

    return ToolProvisioningResult(
        loaded_tools=loaded_tools,
        catalog_tools=catalog_tools,
    )
