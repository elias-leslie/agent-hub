"""
Tests for memory system integration with event publishing.

Demonstrates the full webhook flow for memory systems.
"""

import json
from datetime import datetime, timezone

import pytest

from app.services.events import (
    SessionEvent,
    SessionEventType,
    publish_message,
    publish_tool_use,
    get_event_publisher,
)
from app.services.memory_webhook_handler import (
    MemoryExtractionResult,
    MemoryWebhookHandler,
    extract_memory_from_message,
    extract_pattern_from_tool_use,
    verify_webhook_signature,
)
from app.services.webhooks import compute_signature


class TestMemoryWebhookVerification:
    """Tests for webhook signature verification."""

    def test_verify_valid_signature(self):
        """Valid signatures pass verification."""
        payload = b'{"event_type": "message", "session_id": "sess-1"}'
        secret = "test-secret-key"
        signature = compute_signature(payload.decode(), secret)

        assert verify_webhook_signature(payload, signature, secret) is True

    def test_verify_invalid_signature(self):
        """Invalid signatures fail verification."""
        payload = b'{"event_type": "message"}'
        secret = "test-secret-key"

        assert verify_webhook_signature(payload, "wrong-sig", secret) is False

    def test_verify_tampered_payload(self):
        """Tampered payloads fail verification."""
        original = b'{"event_type": "message", "amount": 100}'
        tampered = b'{"event_type": "message", "amount": 999}'
        secret = "test-secret-key"
        signature = compute_signature(original.decode(), secret)

        assert verify_webhook_signature(tampered, signature, secret) is False


class TestMemoryExtraction:
    """Tests for extracting memories from events."""

    def test_extract_message_with_content(self):
        """Message with meaningful content is extracted."""
        data = {
            "role": "assistant",
            "content": "Here's how to implement the feature...",
            "tokens": 50,
        }
        result = extract_memory_from_message(data)

        assert result is not None
        assert result.content_type == "message"
        assert "implement the feature" in result.content
        assert result.metadata["role"] == "assistant"
        assert result.metadata["tokens"] == 50

    def test_skip_short_messages(self):
        """Very short messages are skipped."""
        data = {"role": "user", "content": "yes"}
        result = extract_memory_from_message(data)
        assert result is None

    def test_skip_empty_messages(self):
        """Empty messages are skipped."""
        data = {"role": "user", "content": ""}
        result = extract_memory_from_message(data)
        assert result is None

    def test_extract_tool_pattern(self):
        """Tool usage is extracted as a pattern."""
        data = {
            "tool_name": "file_read",
            "tool_input": {"path": "/src/main.py", "encoding": "utf-8"},
            "tool_output": "file contents...",
        }
        result = extract_pattern_from_tool_use(data)

        assert result is not None
        assert result.content_type == "tool_pattern"
        assert "file_read" in result.content
        assert "path" in result.content or "path" in result.metadata["input_keys"]
        assert result.metadata["has_output"] is True

    def test_skip_empty_tool_name(self):
        """Tool use without name is skipped."""
        data = {"tool_name": "", "tool_input": {}}
        result = extract_pattern_from_tool_use(data)
        assert result is None


class TestMemoryWebhookHandler:
    """Tests for the full webhook handler."""

    @pytest.fixture
    def handler(self):
        """Create handler with test secret."""
        return MemoryWebhookHandler(secret="test-secret")

    def test_verify_and_parse_valid(self, handler):
        """Valid webhook is verified and parsed."""
        event = {"event_type": "message", "session_id": "sess-1", "data": {}}
        payload = json.dumps(event).encode()
        signature = compute_signature(payload.decode(), handler.secret)

        result = handler.verify_and_parse(payload, signature)
        assert result == event

    def test_verify_and_parse_invalid_signature(self, handler):
        """Invalid signature returns None."""
        payload = b'{"event_type": "message"}'
        result = handler.verify_and_parse(payload, "wrong-sig")
        assert result is None

    def test_verify_and_parse_invalid_json(self, handler):
        """Invalid JSON returns None."""
        payload = b"not json"
        signature = compute_signature(payload.decode(), handler.secret)
        result = handler.verify_and_parse(payload, signature)
        assert result is None

    def test_process_message_event(self, handler):
        """Message events are processed for memory extraction."""
        event = {
            "event_type": "message",
            "session_id": "sess-123",
            "timestamp": "2026-01-06T12:00:00+00:00",
            "data": {
                "role": "user",
                "content": "How do I implement authentication in FastAPI?",
            },
        }

        results = handler.process_event(event)

        assert len(results) == 1
        assert results[0].session_id == "sess-123"
        assert results[0].content_type == "message"
        assert "authentication" in results[0].content

    def test_process_tool_use_event(self, handler):
        """Tool use events are processed for pattern extraction."""
        event = {
            "event_type": "tool_use",
            "session_id": "sess-456",
            "timestamp": "2026-01-06T12:00:00+00:00",
            "data": {
                "tool_name": "code_search",
                "tool_input": {"query": "def authenticate"},
            },
        }

        results = handler.process_event(event)

        assert len(results) == 1
        assert results[0].content_type == "tool_pattern"
        assert "code_search" in results[0].content

    def test_process_complete_event(self, handler):
        """Complete events are logged but don't extract memories."""
        event = {
            "event_type": "complete",
            "session_id": "sess-789",
            "timestamp": "2026-01-06T12:00:00+00:00",
            "data": {
                "input_tokens": 1000,
                "output_tokens": 500,
                "cost": 0.02,
            },
        }

        results = handler.process_event(event)
        assert len(results) == 0  # No memories, just logging


class TestEndToEndIntegration:
    """End-to-end tests for memory system integration."""

    @pytest.fixture(autouse=True)
    def reset_global_publisher(self):
        """Reset global publisher before each test."""
        import app.services.events as events_module
        events_module._event_publisher = None
        yield
        events_module._event_publisher = None

    @pytest.mark.asyncio
    async def test_memory_system_receives_events(self):
        """Memory system receives and processes events via handler."""
        publisher = get_event_publisher()
        handler = MemoryWebhookHandler(secret="integration-test-secret")
        received_events = []

        # Simulate webhook delivery by adding a handler
        def capture_event(event: SessionEvent):
            # In real integration, this would be an HTTP POST to memory system
            # Here we simulate the webhook endpoint processing
            event_dict = event.to_dict()
            payload = json.dumps(event_dict, sort_keys=True)
            signature = compute_signature(payload, handler.secret)

            # Simulate memory system receiving and processing
            parsed = handler.verify_and_parse(payload.encode(), signature)
            if parsed:
                memories = handler.process_event(parsed)
                received_events.extend(memories)

        publisher.add_handler(capture_event)

        # Publish events
        await publish_message(
            session_id="integration-test-session",
            role="user",
            content="Please explain how the event publishing system works",
        )
        await publish_tool_use(
            session_id="integration-test-session",
            tool_name="file_read",
            tool_input={"path": "events.py"},
        )

        # Verify memories were extracted
        assert len(received_events) == 2

        message_memory = received_events[0]
        assert message_memory.content_type == "message"
        assert "event publishing" in message_memory.content

        tool_memory = received_events[1]
        assert tool_memory.content_type == "tool_pattern"
        assert "file_read" in tool_memory.content
