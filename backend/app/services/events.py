"""
Event publishing service for session activity notifications.

Broadcasts events to WebSocket subscribers and triggers webhook callbacks.
Event types: session_start, message, tool_use, complete, error.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class SessionEventType(str, Enum):
    """
    Types of session events that can be published.

    Memory System Integration:
    - MESSAGE events are most relevant for memory extraction
    - TOOL_USE events capture agent actions for pattern learning
    - COMPLETE events signal session end for batch processing
    """

    SESSION_START = "session_start"
    MESSAGE = "message"
    TOOL_USE = "tool_use"
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
        - model: str - Model identifier (e.g., "claude-sonnet-4-5")
        - project_id: str | None - Project for cost tracking

    MESSAGE (memory-relevant):
        - role: str - "user" | "assistant" | "system"
        - content: str - Message text (use for memory extraction)
        - tokens: int | None - Token count

    TOOL_USE (memory-relevant):
        - tool_name: str - Tool identifier
        - tool_input: dict - Tool arguments (patterns for learning)
        - tool_output: Any | None - Tool result

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
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
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
    subscribed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def matches(self, event: SessionEvent) -> bool:
        """Check if this subscription should receive the event."""
        if self.session_ids and event.session_id not in self.session_ids:
            return False
        if self.event_types and event.event_type not in self.event_types:
            return False
        return True


EventHandler = Callable[[SessionEvent], None]


@dataclass
class EventPublisher:
    """
    Publishes session events to WebSocket subscribers and event handlers.

    Manages WebSocket subscriptions filtered by session_id and event_type.
    Handlers can be registered for programmatic event consumption (e.g., webhooks).
    """

    _subscriptions: dict[str, WebSocketSubscription] = field(default_factory=dict)
    _handlers: list[EventHandler] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def add_handler(self, handler: EventHandler) -> None:
        """Add handler for all events (used by webhook dispatcher)."""
        self._handlers.append(handler)

    def remove_handler(self, handler: EventHandler) -> None:
        """Remove event handler."""
        if handler in self._handlers:
            self._handlers.remove(handler)

    async def subscribe(
        self,
        websocket: WebSocket,
        session_ids: set[str] | None = None,
        event_types: set[SessionEventType] | None = None,
    ) -> str:
        """
        Subscribe a WebSocket to session events.

        Args:
            websocket: The WebSocket connection to send events to.
            session_ids: Optional set of session IDs to filter. Empty = all sessions.
            event_types: Optional set of event types to filter. Empty = all types.

        Returns:
            Subscription ID for later unsubscription.
        """
        import uuid

        subscription_id = str(uuid.uuid4())
        subscription = WebSocketSubscription(
            websocket=websocket,
            session_ids=session_ids or set(),
            event_types=event_types or set(),
        )
        async with self._lock:
            self._subscriptions[subscription_id] = subscription
        logger.info(
            f"WebSocket subscribed: {subscription_id} "
            f"(sessions={session_ids or 'all'}, types={event_types or 'all'})"
        )
        return subscription_id

    async def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a WebSocket subscription."""
        async with self._lock:
            if subscription_id in self._subscriptions:
                del self._subscriptions[subscription_id]
                logger.info(f"WebSocket unsubscribed: {subscription_id}")
                return True
        return False

    async def update_subscription(
        self,
        subscription_id: str,
        session_ids: set[str] | None = None,
        event_types: set[SessionEventType] | None = None,
    ) -> bool:
        """Update filters for an existing subscription."""
        async with self._lock:
            if subscription_id not in self._subscriptions:
                return False
            sub = self._subscriptions[subscription_id]
            if session_ids is not None:
                sub.session_ids = session_ids
            if event_types is not None:
                sub.event_types = event_types
        return True

    async def publish(self, event: SessionEvent) -> int:
        """
        Publish an event to all matching subscribers.

        Returns:
            Number of subscribers notified.
        """
        notified = 0
        failed_subscriptions: list[str] = []

        async with self._lock:
            subscriptions = list(self._subscriptions.items())

        for sub_id, sub in subscriptions:
            if not sub.matches(event):
                continue
            try:
                await sub.websocket.send_json(event.to_dict())
                notified += 1
            except Exception as e:
                logger.warning(f"Failed to send event to {sub_id}: {e}")
                failed_subscriptions.append(sub_id)

        for sub_id in failed_subscriptions:
            await self.unsubscribe(sub_id)

        for handler in self._handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Event handler error: {e}")

        if notified > 0 or self._handlers:
            logger.debug(
                f"Published {event.event_type.value} for session {event.session_id} "
                f"to {notified} WebSocket(s) and {len(self._handlers)} handler(s)"
            )

        return notified

    async def get_subscription_count(self) -> int:
        """Get current number of active subscriptions."""
        async with self._lock:
            return len(self._subscriptions)

    async def get_subscriptions_for_session(self, session_id: str) -> int:
        """Get count of subscriptions watching a specific session."""
        async with self._lock:
            count = 0
            for sub in self._subscriptions.values():
                if not sub.session_ids or session_id in sub.session_ids:
                    count += 1
            return count


_event_publisher: EventPublisher | None = None


def get_event_publisher() -> EventPublisher:
    """Get the global event publisher instance."""
    global _event_publisher
    if _event_publisher is None:
        _event_publisher = EventPublisher()
    return _event_publisher


async def publish_session_start(
    session_id: str,
    model: str,
    project_id: str | None = None,
) -> None:
    """Helper to publish session_start event."""
    publisher = get_event_publisher()
    await publisher.publish(
        SessionEvent(
            event_type=SessionEventType.SESSION_START,
            session_id=session_id,
            data={
                "model": model,
                "project_id": project_id,
            },
        )
    )


async def publish_message(
    session_id: str,
    role: str,
    content: str,
    tokens: int | None = None,
) -> None:
    """Helper to publish message event."""
    publisher = get_event_publisher()
    await publisher.publish(
        SessionEvent(
            event_type=SessionEventType.MESSAGE,
            session_id=session_id,
            data={
                "role": role,
                "content": content,
                "tokens": tokens,
            },
        )
    )


async def publish_tool_use(
    session_id: str,
    tool_name: str,
    tool_input: dict[str, Any],
    tool_output: Any | None = None,
) -> None:
    """Helper to publish tool_use event."""
    publisher = get_event_publisher()
    await publisher.publish(
        SessionEvent(
            event_type=SessionEventType.TOOL_USE,
            session_id=session_id,
            data={
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_output": tool_output,
            },
        )
    )


async def publish_complete(
    session_id: str,
    input_tokens: int,
    output_tokens: int,
    cost: float | None = None,
) -> None:
    """Helper to publish complete event."""
    publisher = get_event_publisher()
    await publisher.publish(
        SessionEvent(
            event_type=SessionEventType.COMPLETE,
            session_id=session_id,
            data={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost": cost,
            },
        )
    )


async def publish_error(
    session_id: str,
    error_type: str,
    error_message: str,
) -> None:
    """Helper to publish error event."""
    publisher = get_event_publisher()
    await publisher.publish(
        SessionEvent(
            event_type=SessionEventType.ERROR,
            session_id=session_id,
            data={
                "error_type": error_type,
                "error_message": error_message,
            },
        )
    )
