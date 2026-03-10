"""
Event publishing service for session activity notifications.

Broadcasts events to WebSocket subscribers and triggers webhook callbacks.
Event types: session_start, message, tool_use, complete, error.
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import WebSocket

from .events_models import SessionEvent, SessionEventType, WebSocketSubscription

logger = logging.getLogger(__name__)

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


# Re-export convenience functions from publishers module
# Re-export Hatchet bridge functions
from .events_hatchet_bridge import (  # noqa: E402
    start_hatchet_stream_bridge,
    stop_all_stream_bridges,
)
from .events_publishers import (  # noqa: E402
    publish_complete,
    publish_error,
    publish_message,
    publish_session_start,
    publish_tool_result,
    publish_tool_use,
)

__all__ = [
    "EventHandler",
    "EventPublisher",
    "SessionEvent",
    "SessionEventType",
    "WebSocketSubscription",
    "get_event_publisher",
    "publish_complete",
    "publish_error",
    "publish_message",
    "publish_session_start",
    "publish_tool_result",
    "publish_tool_use",
    "start_hatchet_stream_bridge",
    "stop_all_stream_bridges",
]
