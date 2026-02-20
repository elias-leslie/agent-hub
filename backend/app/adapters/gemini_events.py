"""Unified event structures for tool integration across providers.

These dataclasses represent the canonical event format used by the tool
execution pipeline. Claude SDK messages and OpenAI-compat StreamEvents
are converted into these types by their respective event adapters.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolContentBlock:
    """Content block within a tool event message."""

    type: str
    text: str = ""
    name: str = ""
    input: dict[str, Any] | None = None
    id: str = ""


@dataclass
class ToolMessage:
    """Message container for tool events."""

    content: list[ToolContentBlock]


@dataclass
class ToolEvent:
    """Unified event for tool integration pipeline.

    Event types:
        - "assistant": Contains a ToolMessage with content blocks
        - "tool_result": Contains tool execution result
        - "result": Final accumulated result text
        - "error": Error from provider or tool execution
    """

    type: str
    subtype: str | None = None
    message: ToolMessage | None = None
    content: str = ""
    tool_use_id: str | None = None
    is_error: bool = False
    result: str = ""
    error: str = ""
    duration_ms: int | None = None
