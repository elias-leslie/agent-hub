"""REST API for webhook subscription management."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, HttpUrl

from app.db import get_db_session
from app.models import WebhookSubscription
from app.services.events import SessionEventType
from app.services.webhooks import (
    WebhookConfig,
    generate_webhook_secret,
    get_webhook_dispatcher,
)
from sqlalchemy import select

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class WebhookCreate(BaseModel):
    """Request to create a webhook subscription."""

    url: HttpUrl = Field(..., description="Callback URL for webhook delivery")
    event_types: list[str] = Field(
        ...,
        description="Event types to subscribe to",
        min_length=1,
    )
    project_id: str | None = Field(
        default=None, description="Filter to events from specific project"
    )
    description: str | None = Field(default=None, description="Optional description")


class WebhookResponse(BaseModel):
    """Webhook subscription details."""

    id: int
    url: str
    event_types: list[str]
    project_id: str | None
    description: str | None
    is_active: bool
    created_at: str
    failure_count: int


class WebhookCreateResponse(WebhookResponse):
    """Response after creating a webhook (includes secret)."""

    secret: str = Field(
        ...,
        description="HMAC secret for verifying webhook signatures. "
        "Store securely - this is only shown once.",
    )


class WebhookUpdate(BaseModel):
    """Request to update a webhook subscription."""

    url: HttpUrl | None = Field(default=None, description="New callback URL")
    event_types: list[str] | None = Field(
        default=None, description="New event type filters"
    )
    project_id: str | None = Field(default=None, description="New project filter")
    description: str | None = Field(default=None, description="New description")
    is_active: bool | None = Field(default=None, description="Enable/disable webhook")


def _validate_event_types(event_types: list[str]) -> None:
    """Validate that all event types are valid."""
    valid_types = {e.value for e in SessionEventType}
    for et in event_types:
        if et not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid event type: {et}. Valid types: {sorted(valid_types)}",
            )


def _webhook_to_response(
    webhook: WebhookSubscription, include_secret: bool = False
) -> dict[str, Any]:
    """Convert WebhookSubscription model to response dict."""
    data = {
        "id": webhook.id,
        "url": webhook.url,
        "event_types": webhook.event_types,
        "project_id": webhook.project_id,
        "description": webhook.description,
        "is_active": bool(webhook.is_active),
        "created_at": webhook.created_at.isoformat(),
        "failure_count": webhook.failure_count,
    }
    if include_secret:
        data["secret"] = webhook.secret
    return data


@router.post("", response_model=WebhookCreateResponse, status_code=201)
async def create_webhook(request: WebhookCreate) -> dict[str, Any]:
    """
    Create a new webhook subscription.

    The response includes a secret that must be stored securely.
    This secret is used to verify webhook signatures and is only shown once.
    """
    _validate_event_types(request.event_types)

    secret = generate_webhook_secret()

    async with get_db_session() as session:
        webhook = WebhookSubscription(
            url=str(request.url),
            secret=secret,
            event_types=request.event_types,
            project_id=request.project_id,
            description=request.description,
        )
        session.add(webhook)
        await session.commit()
        await session.refresh(webhook)

        dispatcher = get_webhook_dispatcher()
        dispatcher.register_webhook(
            WebhookConfig(
                id=webhook.id,
                url=webhook.url,
                secret=webhook.secret,
                event_types=webhook.event_types,
                project_id=webhook.project_id,
            )
        )

        logger.info(f"Created webhook {webhook.id} for {request.url}")
        return _webhook_to_response(webhook, include_secret=True)


@router.get("", response_model=list[WebhookResponse])
async def list_webhooks(project_id: str | None = None) -> list[dict[str, Any]]:
    """List all webhook subscriptions, optionally filtered by project."""
    async with get_db_session() as session:
        query = select(WebhookSubscription)
        if project_id:
            query = query.where(WebhookSubscription.project_id == project_id)
        query = query.order_by(WebhookSubscription.created_at.desc())

        result = await session.execute(query)
        webhooks = result.scalars().all()
        return [_webhook_to_response(w) for w in webhooks]


@router.get("/{webhook_id}", response_model=WebhookResponse)
async def get_webhook(webhook_id: int) -> dict[str, Any]:
    """Get a specific webhook subscription."""
    async with get_db_session() as session:
        result = await session.execute(
            select(WebhookSubscription).where(WebhookSubscription.id == webhook_id)
        )
        webhook = result.scalar_one_or_none()
        if not webhook:
            raise HTTPException(status_code=404, detail="Webhook not found")
        return _webhook_to_response(webhook)


@router.patch("/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(webhook_id: int, request: WebhookUpdate) -> dict[str, Any]:
    """Update a webhook subscription."""
    if request.event_types:
        _validate_event_types(request.event_types)

    async with get_db_session() as session:
        result = await session.execute(
            select(WebhookSubscription).where(WebhookSubscription.id == webhook_id)
        )
        webhook = result.scalar_one_or_none()
        if not webhook:
            raise HTTPException(status_code=404, detail="Webhook not found")

        if request.url is not None:
            webhook.url = str(request.url)
        if request.event_types is not None:
            webhook.event_types = request.event_types
        if request.project_id is not None:
            webhook.project_id = request.project_id
        if request.description is not None:
            webhook.description = request.description
        if request.is_active is not None:
            webhook.is_active = 1 if request.is_active else 0

        await session.commit()
        await session.refresh(webhook)

        dispatcher = get_webhook_dispatcher()
        if webhook.is_active:
            dispatcher.register_webhook(
                WebhookConfig(
                    id=webhook.id,
                    url=webhook.url,
                    secret=webhook.secret,
                    event_types=webhook.event_types,
                    project_id=webhook.project_id,
                )
            )
        else:
            dispatcher.unregister_webhook(webhook.id)

        logger.info(f"Updated webhook {webhook_id}")
        return _webhook_to_response(webhook)


@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(webhook_id: int) -> None:
    """Delete a webhook subscription."""
    async with get_db_session() as session:
        result = await session.execute(
            select(WebhookSubscription).where(WebhookSubscription.id == webhook_id)
        )
        webhook = result.scalar_one_or_none()
        if not webhook:
            raise HTTPException(status_code=404, detail="Webhook not found")

        await session.delete(webhook)
        await session.commit()

        dispatcher = get_webhook_dispatcher()
        dispatcher.unregister_webhook(webhook_id)

        logger.info(f"Deleted webhook {webhook_id}")
