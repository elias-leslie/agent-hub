"""Tool provisioning for completion API."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.llm.tool_loop import ToolRunner
from app.llm.types import TextContent, ToolCall, ToolResultMessage
from app.services.tools._tool_constants import (
    MAX_PARALLEL_FILE_WRITES,
    PARALLEL_FILE_WRITE_TOOLS,
    PARALLEL_SAFE_TOOLS,
)
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
    permitted_tools: frozenset[str] | None = None,
) -> ToolRunner:
    """Build the direct tool runner used by completion and streaming paths.

    ``permitted_tools`` is the allow-list of tool calls the caller permits (workflow runs); without it the agent's provisioned tools apply.
    """
    handler = create_direct_handler(
        working_dir=working_dir,
        project_id=project_id,
        session_id=session_id,
        agent_slug=agent_slug,
        permitted_tools=permitted_tools,
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

    base = Path(working_dir) if working_dir else Path.cwd()

    def file_target(call: ToolCall) -> str | None:
        """The resolved file a plain write_file/edit_file call changes (the key for overlapping different files)."""
        path = (call.arguments or {}).get("path")
        if call.name not in PARALLEL_FILE_WRITE_TOOLS or not isinstance(path, str) or not path:
            return None
        return str((base / path).resolve())

    run_tool.is_parallel_safe = lambda call: call.name in PARALLEL_SAFE_TOOLS  # type: ignore[attr-defined]
    run_tool.file_target = file_target  # type: ignore[attr-defined]
    run_tool.max_file_batch = MAX_PARALLEL_FILE_WRITES  # type: ignore[attr-defined]
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


def provision_standard_tools(
    execute_tools: bool,
    tools: list[dict[str, Any]] | None,
    agent_slug: str | None = None,
    defer_tool_loading: bool = False,
) -> ToolProvisioningResult:
    """Auto-provision tools if execute_tools is enabled and no tools provided.

    Uses agent-specific tools from the registry when agent_slug is provided,
    falling back to standard workspace tools otherwise.

    Args:
        execute_tools: Whether tool execution is enabled
        tools: Existing tool definitions (if any)
        agent_slug: Agent slug for agent-specific tool lookup

    Returns:
        Provisioned loaded tools plus the full catalog
    """
    if execute_tools and not tools:
        tools = _resolve_tools(tools, agent_slug)
        logger.info(f"Auto-provided {len(tools)} tools for execute_tools mode (agent={agent_slug})")

    result = tools or []

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
