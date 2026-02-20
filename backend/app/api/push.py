"""Push notification API — shared Web Push service for all projects.

Endpoints for subscription management and push delivery.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services import push_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/push", tags=["push-notifications"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


# ---------- Request/Response schemas ----------


class SubscribeKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribeRequest(BaseModel):
    endpoint: str
    keys: SubscribeKeys


class UnsubscribeRequest(BaseModel):
    endpoint: str


class SendPushRequest(BaseModel):
    title: str
    body: str
    url: str | None = None
    tag: str | None = None
    severity: str = "info"
    task_id: str | None = None
    notification_id: str | None = None
    project_id: str | None = None


# ---------- Endpoints ----------


@router.get("/vapid-key")
async def get_vapid_key() -> dict[str, str]:
    """Return the public VAPID key for browser subscription."""
    from app.config import settings

    if not settings.vapid_public_key:
        raise HTTPException(status_code=503, detail="Web Push not configured")
    return {"public_key": settings.vapid_public_key}


@router.post("/subscriptions")
async def subscribe(req: SubscribeRequest, db: DbDep) -> dict[str, str]:
    """Save a browser push subscription."""
    sub = await push_service.save_subscription(
        db,
        endpoint=req.endpoint,
        p256dh=req.keys.p256dh,
        auth=req.keys.auth,
    )
    logger.info("Push subscription saved: %s", sub.get("id"))
    return {"status": "subscribed", "id": sub.get("id", "")}


@router.delete("/subscriptions")
async def unsubscribe(req: UnsubscribeRequest, db: DbDep) -> dict[str, str]:
    """Remove a push subscription."""
    deleted = await push_service.delete_subscription(db, endpoint=req.endpoint)
    if not deleted:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"status": "unsubscribed"}


@router.post("/send")
async def send_notification(req: SendPushRequest, db: DbDep) -> dict[str, Any]:
    """Send a push notification to all subscribed devices.

    Authenticated via client credentials (internal service calls).
    """
    payload: dict[str, Any] = {
        "title": req.title,
        "body": req.body,
    }
    if req.url:
        payload["url"] = req.url
    if req.tag:
        payload["tag"] = req.tag
    if req.severity:
        payload["severity"] = req.severity
    if req.task_id:
        payload["task_id"] = req.task_id
    if req.notification_id:
        payload["notification_id"] = req.notification_id
    if req.project_id:
        payload["project_id"] = req.project_id

    sent = await push_service.send_push(db, payload=payload)
    return {"status": "sent", "delivered": sent}
