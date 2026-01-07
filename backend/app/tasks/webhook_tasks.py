"""Webhook tasks with retry logic."""

import json
import logging

import httpx
from celery import shared_task

from app.services.webhooks import compute_signature

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(httpx.HTTPError, httpx.TimeoutException),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_kwargs={"max_retries": 5},
)
def send_webhook(self, url: str, payload: dict, headers: dict | None = None) -> dict:
    """Send webhook with exponential backoff retry."""
    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, json=payload, headers=headers or {})
        response.raise_for_status()
        return {"status": response.status_code, "url": url}


@shared_task(
    bind=True,
    autoretry_for=(httpx.HTTPError, httpx.TimeoutException),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_kwargs={"max_retries": 5},
)
def send_webhook_with_signature(
    self,
    webhook_id: int,
    url: str,
    payload: dict,
    secret: str,
) -> dict:
    """
    Send webhook with HMAC signature and exponential backoff retry.

    Args:
        webhook_id: ID of the webhook subscription.
        url: Callback URL.
        payload: Event payload dict.
        secret: HMAC secret for signature.

    Returns:
        Dict with status code and URL.
    """
    payload_json = json.dumps(payload, sort_keys=True)
    signature = compute_signature(payload_json, secret)

    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Signature": signature,
        "X-Webhook-Id": str(webhook_id),
        "User-Agent": "AgentHub-Webhook/1.0",
    }

    logger.info(f"Sending webhook {webhook_id} to {url} (attempt {self.request.retries + 1})")

    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, content=payload_json, headers=headers)
        response.raise_for_status()

    logger.info(f"Webhook {webhook_id} delivered successfully: {response.status_code}")
    return {"status": response.status_code, "url": url, "webhook_id": webhook_id}
