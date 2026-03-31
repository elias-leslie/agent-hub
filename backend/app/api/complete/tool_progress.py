"""Progress tracking utilities for tool execution."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.services.activity_topics import derive_activity_topic

from .tool_models import AgentProgress

logger = logging.getLogger(__name__)


class ProgressTracker:
    """Tracks and reports progress during tool execution."""

    def __init__(
        self,
        callback: Callable[[AgentProgress], Any] | None = None,
        *,
        default_topic: str | None = None,
    ):
        self.callback = callback
        self.default_topic = default_topic
        self.log: list[AgentProgress] = []

    async def _emit_callback(self, progress: AgentProgress) -> None:
        """Report progress without letting observability failures abort execution."""
        if not self.callback:
            return
        try:
            await self.callback(progress)
        except Exception:
            logger.warning(
                "Progress callback failed for turn=%s status=%s; continuing execution",
                progress.turn,
                progress.status,
                exc_info=True,
            )

    async def report_tool_use(
        self,
        turn: int,
        tool_name: str,
        tool_input: Any,
        *,
        topic: str | None = None,
    ) -> None:
        """Report tool use progress."""
        progress = AgentProgress(
            turn=turn,
            status="tool_use",
            message=f"Using tool: {tool_name}",
            topic=topic or derive_activity_topic(tool_name, tool_input, fallback=self.default_topic),
            tool_calls=[{"name": tool_name, "input": tool_input}],
        )
        self.log.append(progress)
        await self._emit_callback(progress)

    async def report_tool_result(
        self,
        turn: int,
        tool_name: str,
        *,
        is_error: bool = False,
        tool_input: Any = None,
        topic: str | None = None,
    ) -> None:
        """Report completion of one tool call."""
        progress = AgentProgress(
            turn=turn,
            status="tool_result",
            message=f"{'Tool failed' if is_error else 'Tool finished'}: {tool_name}",
            topic=topic or derive_activity_topic(tool_name, tool_input, fallback=self.default_topic),
            tool_results=[{"name": tool_name, "is_error": is_error}],
        )
        self.log.append(progress)
        await self._emit_callback(progress)

    async def report_complete(
        self,
        turn: int,
        tool_calls_count: int,
        *,
        topic: str | None = None,
    ) -> None:
        """Report completion progress."""
        progress = AgentProgress(
            turn=turn,
            status="complete",
            message=f"Completed with {tool_calls_count} tool calls",
            topic=topic or self.default_topic,
        )
        self.log.append(progress)
        await self._emit_callback(progress)

    async def report_status(
        self,
        turn: int,
        status: str,
        message: str,
        *,
        topic: str | None = None,
    ) -> None:
        """Report a custom progress update."""
        progress = AgentProgress(
            turn=turn,
            status=status,
            message=message,
            topic=topic or self.default_topic,
        )
        self.log.append(progress)
        await self._emit_callback(progress)
