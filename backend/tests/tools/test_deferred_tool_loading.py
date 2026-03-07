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


@pytest.mark.asyncio
async def test_tool_catalog_checks_nested_tool_permissions() -> None:
    """The virtual dispatcher must not bypass permission checks on the real tool."""
    handler = create_direct_handler(
        permission_config={
            "mode": "granular",
            "deny_list": ["schedule_job"],
            "allow_list": ["tool_catalog"],
        },
        tool_catalog=[
            {
                "name": "schedule_job",
                "description": "Schedule work",
                "input_schema": {"type": "object"},
                "defer_loading": True,
            }
        ],
    )

    result = await handler.execute(
        ToolCall(
            id="t1",
            name="tool_catalog",
            input={"tool_name": "schedule_job", "arguments": {"when": "tomorrow"}},
        )
    )

    assert result.is_error is True
    assert "schedule_job" in result.content
    assert "denied" in result.content


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
