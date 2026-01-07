"""Tests for WebSocket event broadcasting."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.events import (
    EventPublisher,
    SessionEvent,
    SessionEventType,
    WebSocketSubscription,
    get_event_publisher,
    publish_complete,
    publish_error,
    publish_message,
    publish_session_start,
    publish_tool_use,
)


class TestSessionEvent:
    """Tests for SessionEvent dataclass."""

    def test_event_to_dict(self):
        """Event converts to dict with ISO timestamp."""
        event = SessionEvent(
            event_type=SessionEventType.MESSAGE,
            session_id="sess-123",
            data={"role": "user", "content": "hello"},
        )
        d = event.to_dict()
        assert d["event_type"] == "message"
        assert d["session_id"] == "sess-123"
        assert d["data"]["role"] == "user"
        assert "timestamp" in d

    def test_event_default_timestamp(self):
        """Event gets UTC timestamp by default."""
        before = datetime.now(timezone.utc)
        event = SessionEvent(
            event_type=SessionEventType.SESSION_START,
            session_id="sess-1",
        )
        after = datetime.now(timezone.utc)
        assert before <= event.timestamp <= after


class TestWebSocketSubscription:
    """Tests for WebSocketSubscription filtering."""

    def test_matches_all_events_when_no_filters(self):
        """Empty filters match all events."""
        sub = WebSocketSubscription(websocket=MagicMock())
        event = SessionEvent(
            event_type=SessionEventType.MESSAGE,
            session_id="any-session",
        )
        assert sub.matches(event) is True

    def test_matches_specific_session_id(self):
        """Filters by session_id when specified."""
        sub = WebSocketSubscription(
            websocket=MagicMock(),
            session_ids={"sess-1", "sess-2"},
        )
        match = SessionEvent(event_type=SessionEventType.MESSAGE, session_id="sess-1")
        no_match = SessionEvent(event_type=SessionEventType.MESSAGE, session_id="sess-3")
        assert sub.matches(match) is True
        assert sub.matches(no_match) is False

    def test_matches_specific_event_types(self):
        """Filters by event_type when specified."""
        sub = WebSocketSubscription(
            websocket=MagicMock(),
            event_types={SessionEventType.MESSAGE, SessionEventType.ERROR},
        )
        match = SessionEvent(event_type=SessionEventType.MESSAGE, session_id="s")
        no_match = SessionEvent(event_type=SessionEventType.COMPLETE, session_id="s")
        assert sub.matches(match) is True
        assert sub.matches(no_match) is False

    def test_matches_combined_filters(self):
        """Both session_id and event_type filters apply."""
        sub = WebSocketSubscription(
            websocket=MagicMock(),
            session_ids={"sess-1"},
            event_types={SessionEventType.MESSAGE},
        )
        match = SessionEvent(event_type=SessionEventType.MESSAGE, session_id="sess-1")
        wrong_session = SessionEvent(event_type=SessionEventType.MESSAGE, session_id="sess-2")
        wrong_type = SessionEvent(event_type=SessionEventType.ERROR, session_id="sess-1")
        assert sub.matches(match) is True
        assert sub.matches(wrong_session) is False
        assert sub.matches(wrong_type) is False


class TestEventPublisher:
    """Tests for EventPublisher."""

    @pytest.fixture
    def publisher(self):
        """Fresh publisher for each test."""
        return EventPublisher()

    @pytest.mark.asyncio
    async def test_subscribe_returns_id(self, publisher):
        """Subscribe returns a subscription ID."""
        ws = AsyncMock()
        sub_id = await publisher.subscribe(ws)
        assert sub_id is not None
        assert len(sub_id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_subscription(self, publisher):
        """Unsubscribe removes the subscription."""
        ws = AsyncMock()
        sub_id = await publisher.subscribe(ws)
        assert await publisher.get_subscription_count() == 1
        await publisher.unsubscribe(sub_id)
        assert await publisher.get_subscription_count() == 0

    @pytest.mark.asyncio
    async def test_publish_sends_to_matching_subscribers(self, publisher):
        """Publish sends events to matching subscribers."""
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await publisher.subscribe(ws1, session_ids={"sess-1"})
        await publisher.subscribe(ws2, session_ids={"sess-2"})

        event = SessionEvent(event_type=SessionEventType.MESSAGE, session_id="sess-1")
        notified = await publisher.publish(event)

        assert notified == 1
        ws1.send_json.assert_called_once()
        ws2.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_publish_removes_failed_connections(self, publisher):
        """Failed WebSocket sends remove the subscription."""
        ws = AsyncMock()
        ws.send_json.side_effect = Exception("Connection closed")
        await publisher.subscribe(ws)

        event = SessionEvent(event_type=SessionEventType.MESSAGE, session_id="s")
        await publisher.publish(event)

        assert await publisher.get_subscription_count() == 0

    @pytest.mark.asyncio
    async def test_update_subscription_filters(self, publisher):
        """Update subscription changes filters."""
        ws = AsyncMock()
        sub_id = await publisher.subscribe(ws, session_ids={"sess-1"})

        # Initially doesn't match sess-2
        event = SessionEvent(event_type=SessionEventType.MESSAGE, session_id="sess-2")
        await publisher.publish(event)
        ws.send_json.assert_not_called()

        # Update to match sess-2
        await publisher.update_subscription(sub_id, session_ids={"sess-2"})
        await publisher.publish(event)
        ws.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_handler_receives_events(self, publisher):
        """Event handlers receive all published events."""
        received = []
        publisher.add_handler(lambda e: received.append(e))

        event = SessionEvent(event_type=SessionEventType.MESSAGE, session_id="s")
        await publisher.publish(event)

        assert len(received) == 1
        assert received[0].event_type == SessionEventType.MESSAGE

    @pytest.mark.asyncio
    async def test_handler_errors_dont_block_publish(self, publisher):
        """Handler errors don't prevent other handlers from running."""
        received = []
        publisher.add_handler(lambda e: (_ for _ in ()).throw(ValueError("boom")))
        publisher.add_handler(lambda e: received.append(e))

        event = SessionEvent(event_type=SessionEventType.MESSAGE, session_id="s")
        await publisher.publish(event)

        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_get_subscriptions_for_session(self, publisher):
        """Count subscriptions watching a specific session."""
        ws1, ws2, ws3 = AsyncMock(), AsyncMock(), AsyncMock()
        await publisher.subscribe(ws1, session_ids={"sess-1"})
        await publisher.subscribe(ws2, session_ids={"sess-1", "sess-2"})
        await publisher.subscribe(ws3)  # All sessions

        assert await publisher.get_subscriptions_for_session("sess-1") == 3
        assert await publisher.get_subscriptions_for_session("sess-2") == 2
        assert await publisher.get_subscriptions_for_session("sess-3") == 1  # Only ws3


class TestHelperFunctions:
    """Tests for publish_* helper functions."""

    @pytest.fixture(autouse=True)
    def reset_global_publisher(self):
        """Reset global publisher before each test."""
        import app.services.events as events_module
        events_module._event_publisher = None
        yield
        events_module._event_publisher = None

    @pytest.mark.asyncio
    async def test_publish_session_start(self):
        """publish_session_start creates correct event."""
        publisher = get_event_publisher()
        received = []
        publisher.add_handler(lambda e: received.append(e))

        await publish_session_start("sess-1", "claude-sonnet-4-5", "proj-1")

        assert len(received) == 1
        e = received[0]
        assert e.event_type == SessionEventType.SESSION_START
        assert e.session_id == "sess-1"
        assert e.data["model"] == "claude-sonnet-4-5"
        assert e.data["project_id"] == "proj-1"

    @pytest.mark.asyncio
    async def test_publish_message(self):
        """publish_message creates correct event."""
        publisher = get_event_publisher()
        received = []
        publisher.add_handler(lambda e: received.append(e))

        await publish_message("sess-1", "user", "Hello", tokens=5)

        assert len(received) == 1
        e = received[0]
        assert e.event_type == SessionEventType.MESSAGE
        assert e.data["role"] == "user"
        assert e.data["content"] == "Hello"
        assert e.data["tokens"] == 5

    @pytest.mark.asyncio
    async def test_publish_tool_use(self):
        """publish_tool_use creates correct event."""
        publisher = get_event_publisher()
        received = []
        publisher.add_handler(lambda e: received.append(e))

        await publish_tool_use("sess-1", "calculator", {"expr": "2+2"}, "4")

        assert len(received) == 1
        e = received[0]
        assert e.event_type == SessionEventType.TOOL_USE
        assert e.data["tool_name"] == "calculator"
        assert e.data["tool_input"]["expr"] == "2+2"
        assert e.data["tool_output"] == "4"

    @pytest.mark.asyncio
    async def test_publish_complete(self):
        """publish_complete creates correct event."""
        publisher = get_event_publisher()
        received = []
        publisher.add_handler(lambda e: received.append(e))

        await publish_complete("sess-1", 100, 200, cost=0.05)

        assert len(received) == 1
        e = received[0]
        assert e.event_type == SessionEventType.COMPLETE
        assert e.data["input_tokens"] == 100
        assert e.data["output_tokens"] == 200
        assert e.data["cost"] == 0.05

    @pytest.mark.asyncio
    async def test_publish_error(self):
        """publish_error creates correct event."""
        publisher = get_event_publisher()
        received = []
        publisher.add_handler(lambda e: received.append(e))

        await publish_error("sess-1", "RateLimitError", "Too many requests")

        assert len(received) == 1
        e = received[0]
        assert e.event_type == SessionEventType.ERROR
        assert e.data["error_type"] == "RateLimitError"
        assert e.data["error_message"] == "Too many requests"
