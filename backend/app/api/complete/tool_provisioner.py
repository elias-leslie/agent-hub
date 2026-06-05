"""Tool provisioning for completion API."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from app.llm.tool_loop import ToolRunner
from app.llm.types import TextContent, ToolCall, ToolResultMessage
from app.services.tools.base import ToolCall as ServiceToolCall
from app.services.tools.base import ToolCaller
from app.services.tools.catalog import build_deferred_toolset, build_tool_catalog
from app.services.tools.tool_handler import create_direct_handler

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolProvisioningResult:
    """Provisioned tool surface plus the full execution catalog."""

    loaded_tools: list[dict[str, Any]]
    catalog_tools: list[dict[str, Any]]


def build_direct_tool_runner(
    *,
    working_dir: str | None,
    project_id: str | None,
    session_id: str | None,
    agent_slug: str | None,
) -> ToolRunner:
    """Build the direct tool runner used by completion and streaming paths."""
    handler = create_direct_handler(
        working_dir=working_dir,
        project_id=project_id,
        session_id=session_id,
        agent_slug=agent_slug,
    )

    async def run_tool(call: ToolCall) -> ToolResultMessage:
        service_call = ServiceToolCall(
            id=call.id,
            name=call.name,
            input=dict(call.arguments or {}),
            caller=ToolCaller(type="direct"),
        )
        result = await handler.execute(service_call)
        return ToolResultMessage(
            tool_call_id=call.id,
            tool_name=call.name,
            content=[TextContent(text=result.content)],
            is_error=bool(result.is_error),
            timestamp=int(time.time() * 1000),
        )

    return run_tool


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
    agent_slug: str | None,
    visible_tool_names: set[str] | frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Filter tools by project permission tier using Redis cache (best-effort)."""
    if agent_slug == "persona":
        from app.services.tools.persona_tool_surface import (
            filter_persona_runtime_tool_dicts,
            get_persona_runtime_tools_for_tier,
        )

        if visible_tool_names is not None:
            return filter_persona_runtime_tool_dicts(
                result,
                visible_tool_names=visible_tool_names,
            )

        allowed: tuple[str, ...] = ()
        try:
            import json

            import redis

            from app.config import settings

            r = redis.from_url(settings.agent_hub_redis_url, decode_responses=True)
            cached = r.get(f"agent-hub:project-perm:{project_id}")
            r.close()
            tier = json.loads(cached).get("tier") if cached else None
            allowed = get_persona_runtime_tools_for_tier(tier)
        except Exception as e:
            logger.debug("Persona tool provisioning tier filter failed closed: %s", e)
        return filter_persona_runtime_tool_dicts(result, visible_tool_names=allowed)

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
    falling back to standard workspace tools otherwise.

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
    if result and (project_id or agent_slug == "persona"):
        result = _filter_tools_by_tier(
            result,
            project_id or "",
            agent_slug,
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
