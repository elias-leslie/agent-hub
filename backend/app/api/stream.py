"""WebSocket streaming API for real-time completions."""

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError

from app.adapters.base import Message, StreamEvent
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter

logger = logging.getLogger(__name__)

router = APIRouter()


class StreamRequest(BaseModel):
    """Request format for streaming completion."""

    model: str = Field(..., description="Model identifier")
    messages: list[dict[str, str]] = Field(..., description="Conversation messages")
    max_tokens: int = Field(default=4096, ge=1, le=100000)
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)
    session_id: str | None = Field(default=None, description="Optional session ID")


class StreamMessage(BaseModel):
    """Message sent to client during streaming."""

    type: str = Field(..., description="Event type: content, done, or error")
    content: str = Field(default="", description="Content chunk for 'content' events")
    input_tokens: int | None = Field(default=None, description="Input tokens (on 'done')")
    output_tokens: int | None = Field(default=None, description="Output tokens (on 'done')")
    finish_reason: str | None = Field(default=None, description="Why generation stopped")
    error: str | None = Field(default=None, description="Error message for 'error' events")


def _get_provider(model: str) -> str:
    """Determine provider from model name."""
    model_lower = model.lower()
    if "claude" in model_lower:
        return "claude"
    elif "gemini" in model_lower:
        return "gemini"
    return "claude"


def _get_adapter(provider: str) -> ClaudeAdapter | GeminiAdapter:
    """Get adapter instance for provider."""
    if provider == "claude":
        return ClaudeAdapter()
    elif provider == "gemini":
        return GeminiAdapter()
    raise ValueError(f"Unknown provider: {provider}")


def _event_to_message(event: StreamEvent) -> StreamMessage:
    """Convert StreamEvent to StreamMessage."""
    return StreamMessage(
        type=event.type,
        content=event.content,
        input_tokens=event.input_tokens,
        output_tokens=event.output_tokens,
        finish_reason=event.finish_reason,
        error=event.error,
    )


@router.websocket("/stream")
async def stream_completion(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for streaming completions.

    Protocol:
    1. Client connects to /api/stream
    2. Client sends JSON request: {model, messages, max_tokens?, temperature?, session_id?}
    3. Server streams JSON responses: {type: "content"|"done"|"error", content?, ...}
    4. Connection closes after "done" or "error" event
    """
    await websocket.accept()
    logger.info("WebSocket connection accepted")

    try:
        # Receive request from client
        raw_data = await websocket.receive_text()
        logger.debug(f"Received request: {raw_data[:200]}...")

        # Parse and validate request
        try:
            data = json.loads(raw_data)
            request = StreamRequest(**data)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.warning(f"Invalid request: {e}")
            await websocket.send_json(
                StreamMessage(type="error", error=f"Invalid request: {e}").model_dump()
            )
            await websocket.close(code=1003)
            return

        # Get provider and adapter
        provider = _get_provider(request.model)
        try:
            adapter = _get_adapter(provider)
        except ValueError as e:
            await websocket.send_json(
                StreamMessage(type="error", error=str(e)).model_dump()
            )
            await websocket.close(code=1003)
            return

        # Convert messages
        messages = [
            Message(role=m.get("role", "user"), content=m.get("content", ""))  # type: ignore[arg-type]
            for m in request.messages
        ]

        # Stream completion
        logger.info(f"Starting stream for {request.model}")
        async for event in adapter.stream(
            messages=messages,
            model=request.model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
        ):
            message = _event_to_message(event)
            await websocket.send_json(message.model_dump())

            if event.type in ("done", "error"):
                break

        logger.info("Stream completed, closing connection")
        await websocket.close(code=1000)

    except WebSocketDisconnect:
        logger.info("Client disconnected")

    except Exception as e:
        logger.exception(f"Unexpected error in stream: {e}")
        try:
            await websocket.send_json(
                StreamMessage(type="error", error=f"Internal error: {e}").model_dump()
            )
            await websocket.close(code=1011)
        except Exception:
            pass
