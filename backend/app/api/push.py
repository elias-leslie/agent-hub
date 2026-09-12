"""Push notification API — shared Web Push service for all projects.

Endpoints for subscription management and push delivery.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services import push_service
from app.services.push_scope import resolve_push_scope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/push", tags=["push-notifications"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


# ---------- Request/Response schemas ----------


class SubscribeKeys(BaseModel):
    model_config = ConfigDict(extra="forbid")
    p256dh: str
    auth: str


class SubscribeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str
    keys: SubscribeKeys
    application_id: str | None = Field(default=None, min_length=1, max_length=100)
    expiration_time: float | None = Field(default=None, alias="expirationTime")


class UnsubscribeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str
    application_id: str | None = Field(default=None, min_length=1, max_length=100)


class SendPushRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    body: str
    url: str | None = None
    tag: str | None = None
    severity: str = "info"
    task_id: str | None = None
    notification_id: str | None = None
    project_id: str | None = None
    application_id: str | None = Field(default=None, min_length=1, max_length=100)
    # Existing SummitFlow delivery includes this transport-only event label.
    type: str | None = None


# ---------- Endpoints ----------


@router.get("/vapid-key")
async def get_vapid_key() -> dict[str, str]:
    """Return the public VAPID key for browser subscription."""
    from app.config import settings

    if not settings.vapid_public_key:
        raise HTTPException(status_code=503, detail="Web Push not configured")
    return {"public_key": settings.vapid_public_key}


@router.post("/subscriptions")
async def subscribe(req: SubscribeRequest, request: Request, db: DbDep) -> dict[str, str]:
    """Bind registration to a verified application service, not a claimed user."""
    scope = await resolve_push_scope(request, req.application_id)
    try:
        sub = await push_service.save_subscription(
            db, endpoint=req.endpoint, p256dh=req.keys.p256dh, auth=req.keys.auth,
            scope=scope,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    logger.info("Push subscription saved: %s", sub.get("id"))
    return {"status": "subscribed", **sub, "owner_kind": "registered_service_client"}


@router.delete("/subscriptions")
async def unsubscribe(req: UnsubscribeRequest, request: Request, db: DbDep) -> dict[str, str]:
    """Remove a push subscription."""
    scope = await resolve_push_scope(request, req.application_id)
    deleted = await push_service.delete_subscription(db, endpoint=req.endpoint, scope=scope)
    if not deleted:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"status": "unsubscribed", "application_id": scope.application_id}


@router.post("/send")
async def send_notification(req: SendPushRequest, request: Request, db: DbDep) -> dict[str, Any]:
    """Send only to the bound application service principal's subscriptions.

    New scoped consumers verify X-Agent-Hub-Internal plus registered X-Client-Id.
    The isolated SummitFlow compatibility path retains its prior localhost trust.
    """
    scope = await resolve_push_scope(request, req.application_id)
    payload: dict[str, Any] = {
        "title": req.title,
        "body": req.body,
        "application_id": scope.application_id,
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
    if req.type:
        payload["type"] = req.type

    sent = await push_service.send_push(db, payload=payload, scope=scope)
    return {"status": "sent", "delivered": sent, "application_id": scope.application_id,
            "owner_id": scope.owner_id, "legacy_compatibility": scope.include_legacy,
            "delivery_semantics": "Provider accepted; display and human receipt are unobserved."}
