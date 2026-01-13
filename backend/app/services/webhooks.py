"""
Webhook service for delivering session events to external endpoints.

Handles webhook registration, HMAC signature generation, and async delivery.
"""

import hashlib
import hmac
import json
import logging
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from app.services.events import SessionEvent, get_event_publisher

logger = logging.getLogger(__name__)


@dataclass
class WebhookPayload:
    """Payload delivered to webhook endpoints."""

    event_type: str
    session_id: str
    timestamp: str
    data: dict[str, Any]
    webhook_id: int

    def to_json(self) -> str:
        """Convert to JSON string for signing and sending."""
        return json.dumps(
            {
                "event_type": self.event_type,
                "session_id": self.session_id,
                "timestamp": self.timestamp,
                "data": self.data,
                "webhook_id": self.webhook_id,
            },
            sort_keys=True,
        )


def generate_webhook_secret() -> str:
    """Generate a secure random secret for webhook HMAC signatures."""
    return secrets.token_hex(32)


def compute_signature(payload: str, secret: str) -> str:
    """
    Compute HMAC-SHA256 signature for webhook payload.

    Args:
        payload: JSON string of the webhook payload.
        secret: The webhook's secret key.

    Returns:
        Hex-encoded HMAC-SHA256 signature.
    """
    return hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_signature(payload: str, signature: str, secret: str) -> bool:
    """
    Verify a webhook payload signature.

    Args:
        payload: JSON string of the webhook payload.
        signature: The signature provided in the request header.
        secret: The webhook's secret key.

    Returns:
        True if signature is valid.
    """
    expected = compute_signature(payload, secret)
    return hmac.compare_digest(expected, signature)


@dataclass
class WebhookDelivery:
    """Result of a webhook delivery attempt."""

    webhook_id: int
    url: str
    success: bool
    status_code: int | None = None
    error: str | None = None
    duration_ms: float = 0.0


@dataclass
class WebhookConfig:
    """Configuration for a webhook subscription."""

    id: int
    url: str
    secret: str
    event_types: list[str]
    project_id: str | None = None


@dataclass
class WebhookDispatcher:
    """
    Dispatches events to registered webhooks.

    Handles HMAC signing and async HTTP delivery.
    """

    _webhooks: dict[int, WebhookConfig] = field(default_factory=dict)
    _timeout_seconds: float = 10.0
    _max_retries: int = 3

    def register_webhook(self, config: WebhookConfig) -> None:
        """Register a webhook configuration."""
        self._webhooks[config.id] = config
        logger.info(f"Registered webhook {config.id} for events: {config.event_types}")

    def unregister_webhook(self, webhook_id: int) -> bool:
        """Unregister a webhook."""
        if webhook_id in self._webhooks:
            del self._webhooks[webhook_id]
            logger.info(f"Unregistered webhook {webhook_id}")
            return True
        return False

    def _should_deliver(self, config: WebhookConfig, event: SessionEvent) -> bool:
        """Check if webhook should receive this event."""
        return not (config.event_types and event.event_type.value not in config.event_types)

    async def deliver(self, webhook: WebhookConfig, event: SessionEvent) -> WebhookDelivery:
        """
        Deliver an event to a single webhook.

        Args:
            webhook: The webhook configuration.
            event: The event to deliver.

        Returns:
            WebhookDelivery with result details.
        """
        payload = WebhookPayload(
            event_type=event.event_type.value,
            session_id=event.session_id,
            timestamp=event.timestamp.isoformat(),
            data=event.data,
            webhook_id=webhook.id,
        )
        payload_json = payload.to_json()
        signature = compute_signature(payload_json, webhook.secret)

        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": signature,
            "X-Webhook-Id": str(webhook.id),
            "User-Agent": "AgentHub-Webhook/1.0",
        }

        start_time = datetime.now(UTC)
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    webhook.url,
                    content=payload_json,
                    headers=headers,
                )
            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

            success = 200 <= response.status_code < 300
            return WebhookDelivery(
                webhook_id=webhook.id,
                url=webhook.url,
                success=success,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )

        except httpx.TimeoutException:
            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
            return WebhookDelivery(
                webhook_id=webhook.id,
                url=webhook.url,
                success=False,
                error="Timeout",
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000
            return WebhookDelivery(
                webhook_id=webhook.id,
                url=webhook.url,
                success=False,
                error=str(e)[:200],
                duration_ms=duration_ms,
            )

    async def dispatch(
        self, event: SessionEvent, use_celery_on_failure: bool = True
    ) -> list[WebhookDelivery]:
        """
        Dispatch an event to all matching webhooks.

        Args:
            event: The event to dispatch.
            use_celery_on_failure: Queue failed deliveries for Celery retry.

        Returns:
            List of delivery results.
        """
        deliveries = []
        for webhook in self._webhooks.values():
            if self._should_deliver(webhook, event):
                delivery = await self.deliver(webhook, event)
                deliveries.append(delivery)
                if delivery.success:
                    logger.debug(
                        f"Webhook {webhook.id} delivered: {delivery.status_code} "
                        f"({delivery.duration_ms:.0f}ms)"
                    )
                else:
                    logger.warning(
                        f"Webhook {webhook.id} failed: {delivery.error or delivery.status_code}"
                    )
                    if use_celery_on_failure:
                        self._queue_retry(webhook, event)
        return deliveries

    def _queue_retry(self, webhook: WebhookConfig, event: SessionEvent) -> None:
        """Queue a failed webhook delivery for Celery retry."""
        try:
            from app.tasks.webhook_tasks import send_webhook_with_signature

            payload = {
                "event_type": event.event_type.value,
                "session_id": event.session_id,
                "timestamp": event.timestamp.isoformat(),
                "data": event.data,
                "webhook_id": webhook.id,
            }

            send_webhook_with_signature.delay(
                webhook_id=webhook.id,
                url=webhook.url,
                payload=payload,
                secret=webhook.secret,
            )
            logger.info(f"Queued webhook {webhook.id} for Celery retry")
        except Exception as e:
            logger.error(f"Failed to queue webhook {webhook.id} for retry: {e}")


_webhook_dispatcher: WebhookDispatcher | None = None


def get_webhook_dispatcher() -> WebhookDispatcher:
    """Get the global webhook dispatcher instance."""
    global _webhook_dispatcher
    if _webhook_dispatcher is None:
        _webhook_dispatcher = WebhookDispatcher()
    return _webhook_dispatcher


def init_webhook_dispatcher() -> WebhookDispatcher:
    """Initialize the webhook dispatcher and connect it to the event publisher."""
    dispatcher = get_webhook_dispatcher()
    publisher = get_event_publisher()

    def on_event(event: SessionEvent) -> None:
        """Synchronous handler that schedules async dispatch."""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(dispatcher.dispatch(event))  # noqa: RUF006 - fire-and-forget
        except RuntimeError:
            # No running event loop - skip webhook dispatch (e.g., in sync tests)
            logger.debug("No event loop available for webhook dispatch")

    publisher.add_handler(on_event)
    logger.info("Webhook dispatcher initialized and connected to event publisher")
    return dispatcher
