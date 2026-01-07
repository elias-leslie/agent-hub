"""Tests for webhook callback system."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.events import SessionEvent, SessionEventType
from app.services.webhooks import (
    WebhookConfig,
    WebhookDispatcher,
    WebhookPayload,
    compute_signature,
    generate_webhook_secret,
    verify_signature,
)


class TestWebhookSignature:
    """Tests for HMAC signature generation and verification."""

    def test_generate_secret_is_64_hex_chars(self):
        """Generated secrets are 64 hex characters."""
        secret = generate_webhook_secret()
        assert len(secret) == 64
        assert all(c in "0123456789abcdef" for c in secret)

    def test_generate_secret_is_unique(self):
        """Each generated secret is unique."""
        secrets = [generate_webhook_secret() for _ in range(10)]
        assert len(set(secrets)) == 10

    def test_compute_signature_is_deterministic(self):
        """Same payload and secret produce same signature."""
        payload = '{"event": "test"}'
        secret = "test-secret"
        sig1 = compute_signature(payload, secret)
        sig2 = compute_signature(payload, secret)
        assert sig1 == sig2

    def test_compute_signature_changes_with_payload(self):
        """Different payloads produce different signatures."""
        secret = "test-secret"
        sig1 = compute_signature('{"a": 1}', secret)
        sig2 = compute_signature('{"b": 2}', secret)
        assert sig1 != sig2

    def test_compute_signature_changes_with_secret(self):
        """Different secrets produce different signatures."""
        payload = '{"event": "test"}'
        sig1 = compute_signature(payload, "secret-1")
        sig2 = compute_signature(payload, "secret-2")
        assert sig1 != sig2

    def test_verify_signature_valid(self):
        """Valid signatures verify correctly."""
        payload = '{"event": "test"}'
        secret = "test-secret"
        signature = compute_signature(payload, secret)
        assert verify_signature(payload, signature, secret) is True

    def test_verify_signature_invalid(self):
        """Invalid signatures fail verification."""
        payload = '{"event": "test"}'
        secret = "test-secret"
        assert verify_signature(payload, "wrong-signature", secret) is False

    def test_verify_signature_wrong_secret(self):
        """Signature fails with wrong secret."""
        payload = '{"event": "test"}'
        signature = compute_signature(payload, "secret-1")
        assert verify_signature(payload, signature, "secret-2") is False


class TestWebhookPayload:
    """Tests for WebhookPayload."""

    def test_to_json_is_sorted(self):
        """JSON output has sorted keys for consistent signatures."""
        payload = WebhookPayload(
            event_type="message",
            session_id="sess-1",
            timestamp="2026-01-06T12:00:00Z",
            data={"z_key": 1, "a_key": 2},
            webhook_id=1,
        )
        json_str = payload.to_json()
        data = json.loads(json_str)

        keys = list(data.keys())
        assert keys == sorted(keys)

    def test_to_json_includes_all_fields(self):
        """JSON includes all required fields."""
        payload = WebhookPayload(
            event_type="session_start",
            session_id="sess-123",
            timestamp="2026-01-06T12:00:00Z",
            data={"model": "claude"},
            webhook_id=42,
        )
        data = json.loads(payload.to_json())
        assert data["event_type"] == "session_start"
        assert data["session_id"] == "sess-123"
        assert data["webhook_id"] == 42
        assert data["data"]["model"] == "claude"


class TestWebhookConfig:
    """Tests for WebhookConfig filtering."""

    def test_config_stores_fields(self):
        """Config stores all provided fields."""
        config = WebhookConfig(
            id=1,
            url="https://example.com/hook",
            secret="secret123",
            event_types=["message", "error"],
            project_id="proj-1",
        )
        assert config.id == 1
        assert config.url == "https://example.com/hook"
        assert config.event_types == ["message", "error"]


class TestWebhookDispatcher:
    """Tests for WebhookDispatcher."""

    @pytest.fixture
    def dispatcher(self):
        """Fresh dispatcher for each test."""
        return WebhookDispatcher()

    @pytest.fixture
    def webhook(self):
        """Sample webhook config."""
        return WebhookConfig(
            id=1,
            url="https://example.com/hook",
            secret="test-secret",
            event_types=["message", "complete"],
        )

    @pytest.fixture
    def event(self):
        """Sample session event."""
        return SessionEvent(
            event_type=SessionEventType.MESSAGE,
            session_id="sess-1",
            data={"content": "hello"},
        )

    def test_register_webhook(self, dispatcher, webhook):
        """Register adds webhook to dispatcher."""
        dispatcher.register_webhook(webhook)
        assert len(dispatcher._webhooks) == 1
        assert 1 in dispatcher._webhooks

    def test_unregister_webhook(self, dispatcher, webhook):
        """Unregister removes webhook."""
        dispatcher.register_webhook(webhook)
        result = dispatcher.unregister_webhook(1)
        assert result is True
        assert len(dispatcher._webhooks) == 0

    def test_unregister_nonexistent_returns_false(self, dispatcher):
        """Unregister nonexistent webhook returns False."""
        assert dispatcher.unregister_webhook(999) is False

    def test_should_deliver_matches_event_type(self, dispatcher, webhook, event):
        """Webhook receives events matching its event_types filter."""
        assert dispatcher._should_deliver(webhook, event) is True

        error_event = SessionEvent(
            event_type=SessionEventType.ERROR,
            session_id="sess-1",
        )
        assert dispatcher._should_deliver(webhook, error_event) is False

    def test_should_deliver_all_when_no_filter(self, dispatcher, event):
        """Webhook with empty event_types receives all events."""
        webhook = WebhookConfig(
            id=1,
            url="https://example.com/hook",
            secret="secret",
            event_types=[],
        )
        assert dispatcher._should_deliver(webhook, event) is True

    @pytest.mark.asyncio
    async def test_deliver_sends_correct_request(self, dispatcher, webhook, event):
        """Deliver sends POST with signature headers."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = MagicMock(status_code=200)
            mock_client_class.return_value = mock_client

            delivery = await dispatcher.deliver(webhook, event)

            assert delivery.success is True
            assert delivery.status_code == 200

            # Verify signature header was included
            call_kwargs = mock_client.post.call_args.kwargs
            assert "X-Webhook-Signature" in call_kwargs["headers"]
            assert call_kwargs["headers"]["X-Webhook-Id"] == "1"

    @pytest.mark.asyncio
    async def test_deliver_handles_timeout(self, dispatcher, webhook, event):
        """Deliver handles timeout gracefully."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.side_effect = httpx.TimeoutException("timeout")
            mock_client_class.return_value = mock_client

            delivery = await dispatcher.deliver(webhook, event)

            assert delivery.success is False
            assert delivery.error == "Timeout"

    @pytest.mark.asyncio
    async def test_deliver_handles_http_error(self, dispatcher, webhook, event):
        """Deliver handles HTTP errors gracefully."""
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = MagicMock(status_code=500)
            mock_client_class.return_value = mock_client

            delivery = await dispatcher.deliver(webhook, event)

            assert delivery.success is False
            assert delivery.status_code == 500

    @pytest.mark.asyncio
    async def test_dispatch_sends_to_matching_webhooks(self, dispatcher, event):
        """Dispatch sends to all matching webhooks."""
        webhook1 = WebhookConfig(
            id=1, url="https://a.com", secret="s1", event_types=["message"]
        )
        webhook2 = WebhookConfig(
            id=2, url="https://b.com", secret="s2", event_types=["error"]
        )
        dispatcher.register_webhook(webhook1)
        dispatcher.register_webhook(webhook2)

        with patch.object(dispatcher, "deliver", new_callable=AsyncMock) as mock_deliver:
            from app.services.webhooks import WebhookDelivery
            mock_deliver.return_value = WebhookDelivery(
                webhook_id=1, url="https://a.com", success=True, status_code=200
            )

            deliveries = await dispatcher.dispatch(event, use_celery_on_failure=False)

            assert len(deliveries) == 1
            mock_deliver.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_queues_retry_on_failure(self, dispatcher, webhook, event):
        """Failed deliveries are queued for Celery retry."""
        dispatcher.register_webhook(webhook)

        with patch.object(dispatcher, "deliver", new_callable=AsyncMock) as mock_deliver:
            from app.services.webhooks import WebhookDelivery
            mock_deliver.return_value = WebhookDelivery(
                webhook_id=1, url="https://example.com", success=False, error="Timeout"
            )

            with patch.object(dispatcher, "_queue_retry") as mock_queue:
                await dispatcher.dispatch(event, use_celery_on_failure=True)
                mock_queue.assert_called_once_with(webhook, event)


class TestCeleryTask:
    """Tests for Celery webhook task."""

    def test_send_webhook_with_signature_computes_signature(self):
        """Task computes correct signature."""
        from app.tasks.webhook_tasks import send_webhook_with_signature

        with patch("app.tasks.webhook_tasks.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.__enter__.return_value = mock_client
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.post.return_value = mock_response
            mock_client_class.return_value = mock_client

            payload = {"event_type": "message", "session_id": "sess-1"}
            secret = "test-secret"

            # Call the task synchronously (bypasses Celery)
            # Note: When bind=True, Celery wraps the function and hides self
            result = send_webhook_with_signature.run(
                webhook_id=1,
                url="https://example.com/hook",
                payload=payload,
                secret=secret,
            )

            assert result["status"] == 200
            assert result["webhook_id"] == 1

            # Verify signature was in headers
            call_kwargs = mock_client.post.call_args.kwargs
            assert "X-Webhook-Signature" in call_kwargs["headers"]

            # Verify signature is correct
            payload_json = json.dumps(payload, sort_keys=True)
            expected_sig = compute_signature(payload_json, secret)
            assert call_kwargs["headers"]["X-Webhook-Signature"] == expected_sig
