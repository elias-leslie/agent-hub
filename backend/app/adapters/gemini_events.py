"""Mock event structures for Gemini tool integration."""

from dataclasses import dataclass
from typing import Any


@dataclass
class MockContentBlock:
    """Mock content block for tool events."""

    type: str
    text: str = ""
    name: str = ""
    input: dict[str, Any] | None = None
    id: str = ""


@dataclass
class MockMessage:
    """Mock message for tool events."""

    content: list[MockContentBlock]


@dataclass
class MockEvent:
    """Mock event for tool integration."""

    type: str
    subtype: str | None = None
    message: MockMessage | None = None
    content: str = ""
    tool_use_id: str | None = None
    is_error: bool = False
    result: str = ""
    error: str = ""
    duration_ms: int | None = None
