"""
Data models for session events.

Event types and payloads for session activity notifications.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fastapi import WebSocket


class SessionEventType(StrEnum):
    """
    Types of session events that can be published.

    Memory System Integration:
    - MESSAGE events are most relevant for memory extraction
    - TOOL_USE / TOOL_RESULT events capture agent actions for pattern learning
    - COMPLETE events signal session end for batch processing
    """

    SESSION_START = "session_start"
    MESSAGE = "message"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class SessionEvent:
    """
    Event payload for session activity notifications.

    All events include:
    - event_type: One of SessionEventType values
    - session_id: Unique session identifier (UUID)
    - timestamp: ISO 8601 UTC timestamp
    - data: Event-specific payload

    Event-specific data fields:

    SESSION_START:
        - model: str - Served model telemetry from Agent Hub catalog
        - project_id: str | None - Project for cost tracking

    MESSAGE (memory-relevant):
        - role: str - "user" | "assistant" | "system"
        - content: str - Message text (use for memory extraction)
        - tokens: int | None - Token count

    TOOL_USE (memory-relevant):
        - tool_name: str - Tool identifier
        - tool_input: dict - Tool arguments (patterns for learning)
        - tool_output: Any | None - Tool result

    TOOL_RESULT (memory-relevant):
        - tool_name: str | None - Tool identifier
        - tool_output: Any | None - Tool result payload
        - duration_ms: int | None - Execution duration

    COMPLETE:
        - input_tokens: int - Total input tokens
        - output_tokens: int - Total output tokens
        - cost: float | None - Estimated cost USD

    ERROR:
        - error_type: str - Error class name
        - error_message: str - Error description
    """

    event_type: SessionEventType
    session_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert event to JSON-serializable dict."""
        return {
            "event_type": self.event_type.value,
            "session_id": self.session_id,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
        }


@dataclass
class WebSocketSubscription:
    """A WebSocket client subscribed to session events."""

    websocket: WebSocket
    session_ids: set[str] = field(default_factory=set)
    event_types: set[SessionEventType] = field(default_factory=set)
    subscribed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def matches(self, event: SessionEvent) -> bool:
        """Check if this subscription should receive the event."""
        if self.session_ids and event.session_id not in self.session_ids:
            return False
        return not (self.event_types and event.event_type not in self.event_types)
