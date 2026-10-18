"""WebSocket API for session event subscriptions."""

import json
import logging
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.config import settings
from app.core.access_identity import resolve_caller
from app.services.events import SessionEventType, get_event_publisher

logger = logging.getLogger(__name__)
router = APIRouter()


class SubscribeRequest(BaseModel):
    """Request to subscribe to session events."""

    type: Literal["subscribe", "unsubscribe", "update"] = Field(..., description="Action type")
    session_ids: list[str] | None = Field(default=None, description="Session IDs to filter")
    event_types: list[str] | None = Field(default=None, description="Event types to filter")


class SubscribeResponse(BaseModel):
    """Response to subscription actions."""

    type: str = Field(..., description="Response type: subscribed, updated, error")
    subscription_id: str | None = Field(default=None)
    message: str | None = Field(default=None)


async def _send_error(websocket: WebSocket, message: str) -> None:
    await websocket.send_json(SubscribeResponse(type="error", message=message).model_dump())


def _parse_event_types(strs: list[str]) -> tuple[set[SessionEventType], str | None]:
    """Parse strings into SessionEventType values; returns (set, error_or_None)."""
    result: set[SessionEventType] = set()
    for et in strs:
        try:
            result.add(SessionEventType(et))
        except ValueError:
            return set(), f"Invalid event type: {et}"
    return result, None


async def _handle_subscribe(
    websocket: WebSocket, data: dict[str, object], subscription_id: str | None
) -> str | None:
    """Handle 'subscribe'; returns new subscription_id (or unchanged on error)."""
    if subscription_id:
        await _send_error(websocket, "Already subscribed. Use 'update' to change filters.")
        return subscription_id
    session_ids: set[str] = set(data.get("session_ids") or [])
    event_type_strs: list[str] = data.get("event_types") or []  # type: ignore[assignment]
    event_types, error = _parse_event_types(event_type_strs)
    if error:
        await _send_error(websocket, error)
        return subscription_id
    new_id = await get_event_publisher().subscribe(
        websocket=websocket,
        session_ids=session_ids or None,
        event_types=event_types or None,
    )
    await websocket.send_json(SubscribeResponse(type="subscribed", subscription_id=new_id).model_dump())
    return new_id


async def _handle_update(
    websocket: WebSocket, data: dict[str, object], subscription_id: str | None
) -> None:
    """Handle 'update' to change subscription filters."""
    if not subscription_id:
        await _send_error(websocket, "Not subscribed. Send 'subscribe' first.")
        return
    raw_sessions = data.get("session_ids")
    updated_sessions: set[str] | None = (
        set(raw_sessions) if raw_sessions is not None else None
    )
    raw_types = data.get("event_types")
    updated_types: set[SessionEventType] | None = None
    if raw_types is not None:
        updated_types = set()
        for et in raw_types:  # type: ignore[union-attr]
            try:
                updated_types.add(SessionEventType(et))
            except ValueError:
                logger.warning(f"Ignoring invalid event type in update: {et}")
    await get_event_publisher().update_subscription(
        subscription_id=subscription_id, session_ids=updated_sessions, event_types=updated_types
    )
    await websocket.send_json(
        SubscribeResponse(type="updated", subscription_id=subscription_id).model_dump()
    )


async def _handle_unsubscribe(websocket: WebSocket, subscription_id: str | None) -> None:
    """Handle 'unsubscribe': remove subscription and close the connection."""
    if subscription_id:
        await get_event_publisher().unsubscribe(subscription_id)
    await websocket.send_json(
        SubscribeResponse(
            type="unsubscribed", message="Subscription removed. Closing connection."
        ).model_dump()
    )
    await websocket.close(code=1000)


async def _dispatch(
    websocket: WebSocket, raw_data: str, subscription_id: str | None
) -> tuple[str | None, bool]:
    """Parse and dispatch one WebSocket message; returns (subscription_id, should_close)."""
    try:
        data: dict[str, object] = json.loads(raw_data)
    except json.JSONDecodeError:
        await _send_error(websocket, "Invalid JSON")
        return subscription_id, False
    request_type = data.get("type")
    if request_type == "subscribe":
        return await _handle_subscribe(websocket, data, subscription_id), False
    if request_type == "update":
        await _handle_update(websocket, data, subscription_id)
        return subscription_id, False
    if request_type == "unsubscribe":
        await _handle_unsubscribe(websocket, subscription_id)
        return None, True
    await _send_error(websocket, f"Unknown request type: {request_type}")
    return subscription_id, False


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _origin_allowed(websocket: WebSocket) -> bool:
    """Block cross-site browser pages from reading the event stream.

    Browsers always send Origin on WebSocket upgrades and CORS does not apply,
    so any visited site could otherwise subscribe via ws://localhost. Non-browser
    clients send no Origin and stay allowed.
    """
    origin = websocket.headers.get("origin")
    if not origin:
        return True
    if origin in settings.cors_origins:
        return True
    parts = urlsplit(origin)
    if parts.hostname in _LOOPBACK_HOSTS:
        return True
    return parts.netloc == websocket.headers.get("host")


def _caller_is_owner(websocket: WebSocket) -> bool:
    """The event stream carries session content, so only the owner principal may read it."""
    try:
        return resolve_caller(websocket).is_owner
    except HTTPException:
        return False


@router.websocket("/events")
async def events_websocket(websocket: WebSocket) -> None:
    """WebSocket endpoint; connect → subscribe → receive events → update/unsubscribe."""
    if not _origin_allowed(websocket):
        logger.warning("Rejected events WebSocket from origin %s", websocket.headers.get("origin"))
        await websocket.close(code=1008)
        return
    if not _caller_is_owner(websocket):
        logger.warning("Rejected events WebSocket without an owner principal")
        await websocket.close(code=1008)
        return
    await websocket.accept()
    logger.info("Events WebSocket connection accepted")
    subscription_id: str | None = None
    try:
        while True:
            raw_data = await websocket.receive_text()
            subscription_id, should_close = await _dispatch(websocket, raw_data, subscription_id)
            if should_close:
                return
    except WebSocketDisconnect:
        logger.info(f"Events WebSocket client disconnected (sub={subscription_id})")
    except Exception as e:
        logger.exception(f"Error in events WebSocket: {e}")
    finally:
        if subscription_id:
            await get_event_publisher().unsubscribe(subscription_id)
