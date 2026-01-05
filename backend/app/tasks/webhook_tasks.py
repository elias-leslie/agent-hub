"""Webhook tasks with retry logic."""

import httpx
from celery import shared_task


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
