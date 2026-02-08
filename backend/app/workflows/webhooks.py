"""Webhook delivery workflow."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from hatchet_sdk import Context
from pydantic import BaseModel

from app.hatchet_app import hatchet
from app.services.webhooks import compute_signature

logger = logging.getLogger(__name__)


class WebhookInput(BaseModel):
    webhook_id: int
    url: str
    payload: dict[str, Any]
    secret: str


@hatchet.task(
    name="webhook-delivery",
    input_validator=WebhookInput,
    execution_timeout="60s",
    retries=5,
    backoff_factor=2.0,
    backoff_max_seconds=300,
)
async def webhook_delivery_task(input: WebhookInput, ctx: Context) -> dict[str, Any]:
    payload_json = json.dumps(input.payload, sort_keys=True)
    signature = compute_signature(payload_json, input.secret)

    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Signature": signature,
        "X-Webhook-Id": str(input.webhook_id),
        "User-Agent": "AgentHub-Webhook/1.0",
    }

    logger.info(
        "Sending webhook %d to %s (attempt %d)",
        input.webhook_id,
        input.url,
        ctx.retry_count + 1,
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(input.url, content=payload_json, headers=headers)
        response.raise_for_status()

    logger.info(
        "Webhook %d delivered: %d", input.webhook_id, response.status_code
    )
    return {
        "status": response.status_code,
        "url": input.url,
        "webhook_id": input.webhook_id,
    }
