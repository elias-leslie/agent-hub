"""Progress tracking utilities for tool execution."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .tool_models import AgentProgress


class ProgressTracker:
    """Tracks and reports progress during tool execution."""

    def __init__(self, callback: Callable[[AgentProgress], Any] | None = None):
        self.callback = callback
        self.log: list[AgentProgress] = []

    async def report_tool_use(
        self,
        turn: int,
        tool_name: str,
        tool_input: Any,
    ) -> None:
        """Report tool use progress."""
        progress = AgentProgress(
            turn=turn,
            status="tool_use",
            message=f"Using tool: {tool_name}",
            tool_calls=[{"name": tool_name, "input": tool_input}],
        )
        self.log.append(progress)
        if self.callback:
            await self.callback(progress)

    async def report_complete(
        self,
        turn: int,
        tool_calls_count: int,
    ) -> None:
        """Report completion progress."""
        progress = AgentProgress(
            turn=turn,
            status="complete",
            message=f"Completed with {tool_calls_count} tool calls",
        )
        self.log.append(progress)
        if self.callback:
            await self.callback(progress)
