"""Tests for deferred tool loading and catalog-backed execution."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.tools.base import Tool, ToolCall
from app.services.tools.catalog import build_deferred_toolset
from app.services.tools.tool_handler import create_direct_handler


def test_build_deferred_toolset_adds_virtual_catalog_tools() -> None:
    """Deferred mode should keep hot tools loaded and add search/catalog tools."""
    tools = [
        Tool(
            name="manage_tasks",
            description="Task operations",
            input_schema={"type": "object"},
            category="tasks",
        ),
        Tool(
            name="schedule_job",
            description="Schedule work",
            input_schema={"type": "object"},
            category="persona",
            search_keywords=["schedule", "cron"],
            usage_examples=["Schedule a follow-up for tomorrow morning."],
            defer_loading=True,
        ),
    ]

    loaded_tools, catalog_tools = build_deferred_toolset(tools)

    assert [tool["name"] for tool in loaded_tools] == [
        "manage_tasks",
        "tool_search",
        "tool_catalog",
    ]
    assert [tool["name"] for tool in catalog_tools] == [
        "manage_tasks",
        "schedule_job",
    ]
    schedule_entry = catalog_tools[1]
    assert schedule_entry["defer_loading"] is True
    assert schedule_entry["search_keywords"] == ["schedule", "cron"]
    assert schedule_entry["usage_examples"] == [
        "Schedule a follow-up for tomorrow morning."
    ]


def test_persona_heartbeat_hot_tools_stay_loaded_in_deferred_mode() -> None:
    """Heartbeat-critical persona tools must remain directly callable."""
    from app.services.tools.tool_definitions import get_agent_tool_specs

    persona_tools = get_agent_tool_specs("persona")
    assert persona_tools is not None

    loaded_tools, _catalog_tools = build_deferred_toolset(persona_tools)
    loaded_names = {tool["name"] for tool in loaded_tools}

    assert "manage_tasks" in loaded_names
    assert "query_sessions" in loaded_names
    assert "schedule_job" in loaded_names
    assert "manage_feedback" in loaded_names
    assert "inspect_session" in loaded_names


@pytest.mark.asyncio
async def test_tool_catalog_dispatches_to_real_tool() -> None:
    """The virtual dispatcher should call the underlying executor tool by name."""
    handler = create_direct_handler(
        tool_catalog=[
            {
                "name": "schedule_job",
                "description": "Schedule work",
                "input_schema": {"type": "object"},
                "defer_loading": True,
            }
        ],
    )
    handler._executor.dispatch = AsyncMock(return_value="scheduled")  # type: ignore[attr-defined]

    result = await handler.execute(
        ToolCall(
            id="t1",
            name="tool_catalog",
            input={"tool_name": "schedule_job", "arguments": {"when": "tomorrow"}},
        )
    )

    assert result.is_error is False
    assert result.content == "scheduled"
    handler._executor.dispatch.assert_awaited_once_with(
        "schedule_job", {"when": "tomorrow"}
    )


@pytest.mark.asyncio
async def test_tool_catalog_dispatches_top_level_arguments_to_real_tool() -> None:
    """Catalog compatibility should preserve top-level args from provider tool calls."""
    handler = create_direct_handler(
        tool_catalog=[
            {
                "name": "manage_memory_tags",
                "description": "Update memory tags",
                "input_schema": {"type": "object"},
                "defer_loading": True,
            }
        ],
    )
    handler._executor.dispatch = AsyncMock(return_value="updated")  # type: ignore[attr-defined]

    result = await handler.execute(
        ToolCall(
            id="t2",
            name="tool_catalog",
            input={
                "tool_name": "manage_memory_tags",
                "action": "add_tags",
                "memory_uuid": "mem-123",
                "tags": ["routing"],
            },
        )
    )

    assert result.is_error is False
    assert result.content == "updated"
    handler._executor.dispatch.assert_awaited_once_with(
        "manage_memory_tags",
        {
            "action": "add_tags",
            "memory_uuid": "mem-123",
            "tags": ["routing"],
        },
    )
