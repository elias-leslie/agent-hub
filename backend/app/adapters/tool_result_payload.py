"""Normalize tool handler return values for provider adapter loops."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolResultPayload:
    content: str
    is_error: bool = False
    duration_ms: int | None = None


def normalize_tool_handler_result(raw: Any) -> ToolResultPayload:
    """Accept legacy string handlers and richer ToolResult-like objects."""
    if hasattr(raw, "content"):
        return ToolResultPayload(
            content=str(getattr(raw, "content", "") or ""),
            is_error=bool(getattr(raw, "is_error", False)),
            duration_ms=getattr(raw, "duration_ms", None),
        )
    return ToolResultPayload(content=str(raw or ""))
