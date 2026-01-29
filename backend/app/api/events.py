"""WebSocket API for session event subscriptions."""

import json
import logging
from typing import Any, Literal

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.services.events import (
    SessionEventType,
    get_event_publisher,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class SubscribeRequest(BaseModel):
    """Request to subscribe to session events."""

    type: Literal["subscribe", "unsubscribe", "update"] = Field(..., description="Action type")
    session_ids: list[str] | None = Field(
        default=None, description="Session IDs to filter (empty = all)"
    )
    event_types: list[str] | None = Field(
        default=None, description="Event types to filter (empty = all)"
    )


class SubscribeResponse(BaseModel):
    """Response to subscription actions."""

    type: str = Field(..., description="Response type: subscribed, updated, error")
    subscription_id: str | None = Field(default=None)
    message: str | None = Field(default=None)


@router.websocket("/events")
async def events_websocket(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for subscribing to session events.

    Protocol:
    1. Client connects to /api/events
    2. Client sends: {"type": "subscribe", "session_ids": [...], "event_types": [...]}
       - session_ids: optional, filters to specific sessions. Empty/null = all sessions.
       - event_types: optional, filters to specific event types. Empty/null = all types.
         Valid types: session_start, message, tool_use, complete, error
    3. Server responds: {"type": "subscribed", "subscription_id": "..."}
    4. Server pushes events as they occur:
       {"event_type": "...", "session_id": "...", "timestamp": "...", "data": {...}}
    5. Client can update filters: {"type": "update", "session_ids": [...], "event_types": [...]}
    6. Client can unsubscribe: {"type": "unsubscribe"}
    7. Connection closes on client disconnect or unsubscribe
    """
    await websocket.accept()
    logger.info("Events WebSocket connection accepted")

    publisher = get_event_publisher()
    subscription_id: str | None = None

    try:
        while True:
            raw_data = await websocket.receive_text()

            try:
                data = json.loads(raw_data)
                request_type = data.get("type")

                if request_type == "subscribe":
                    if subscription_id:
                        await websocket.send_json(
                            SubscribeResponse(
                                type="error",
                                message="Already subscribed. Use 'update' to change filters.",
                            ).model_dump()
                        )
                        continue

                    session_ids = set(data.get("session_ids") or [])
                    event_type_strs = data.get("event_types") or []

                    event_types: set[SessionEventType] = set()
                    for et in event_type_strs:
                        try:
                            event_types.add(SessionEventType(et))
                        except ValueError:
                            await websocket.send_json(
                                SubscribeResponse(
                                    type="error",
                                    message=f"Invalid event type: {et}",
                                ).model_dump()
                            )
                            continue

                    subscription_id = await publisher.subscribe(
                        websocket=websocket,
                        session_ids=session_ids if session_ids else None,
                        event_types=event_types if event_types else None,
                    )

                    await websocket.send_json(
                        SubscribeResponse(
                            type="subscribed",
                            subscription_id=subscription_id,
                        ).model_dump()
                    )

                elif request_type == "update":
                    if not subscription_id:
                        await websocket.send_json(
                            SubscribeResponse(
                                type="error",
                                message="Not subscribed. Send 'subscribe' first.",
                            ).model_dump()
                        )
                        continue

                    updated_session_ids: set[Any] | None = (
                        set(data.get("session_ids"))
                        if data.get("session_ids") is not None
                        else None
                    )
                    updated_event_type_strs = data.get("event_types")

                    updated_event_types: set[SessionEventType] | None = None
                    if updated_event_type_strs is not None:
                        updated_event_types = set()
                        for et in updated_event_type_strs:
                            try:
                                updated_event_types.add(SessionEventType(et))
                            except ValueError:
                                logger.warning(f"Ignoring invalid event type in update: {et}")

                    await publisher.update_subscription(
                        subscription_id=subscription_id,
                        session_ids=updated_session_ids,
                        event_types=updated_event_types,
                    )

                    await websocket.send_json(
                        SubscribeResponse(
                            type="updated",
                            subscription_id=subscription_id,
                        ).model_dump()
                    )

                elif request_type == "unsubscribe":
                    if subscription_id:
                        await publisher.unsubscribe(subscription_id)
                        subscription_id = None
                    await websocket.send_json(
                        SubscribeResponse(
                            type="unsubscribed",
                            message="Subscription removed. Closing connection.",
                        ).model_dump()
                    )
                    await websocket.close(code=1000)
                    return

                else:
                    await websocket.send_json(
                        SubscribeResponse(
                            type="error",
                            message=f"Unknown request type: {request_type}",
                        ).model_dump()
                    )

            except json.JSONDecodeError:
                await websocket.send_json(
                    SubscribeResponse(
                        type="error",
                        message="Invalid JSON",
                    ).model_dump()
                )

    except WebSocketDisconnect:
        logger.info(f"Events WebSocket client disconnected (sub={subscription_id})")
    except Exception as e:
        logger.exception(f"Error in events WebSocket: {e}")
    finally:
        if subscription_id:
            await publisher.unsubscribe(subscription_id)
