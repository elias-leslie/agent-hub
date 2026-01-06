"""WebSocket streaming API for real-time completions."""

import asyncio
import json
import logging
from typing import Any, Literal

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError

from app.adapters.base import Message, StreamEvent
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter

logger = logging.getLogger(__name__)

router = APIRouter()


class StreamRequest(BaseModel):
    """Request format for streaming completion."""

    type: Literal["request", "cancel"] = Field(
        default="request", description="Message type: 'request' to start, 'cancel' to stop"
    )
    model: str | None = Field(default=None, description="Model identifier (required for 'request')")
    messages: list[dict[str, str]] | None = Field(
        default=None, description="Conversation messages (required for 'request')"
    )
    max_tokens: int = Field(default=4096, ge=1, le=100000)
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)
    session_id: str | None = Field(default=None, description="Optional session ID")


class StreamMessage(BaseModel):
    """Message sent to client during streaming."""

    type: str = Field(
        ..., description="Event type: content, done, cancelled, or error"
    )
    content: str = Field(default="", description="Content chunk for 'content' events")
    input_tokens: int | None = Field(default=None, description="Input tokens (on 'done'/'cancelled')")
    output_tokens: int | None = Field(
        default=None, description="Output tokens (on 'done'/'cancelled')"
    )
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


class StreamingState:
    """State for an active streaming session."""

    def __init__(self) -> None:
        self.cancelled = False
        self.input_tokens = 0
        self.output_tokens = 0
        self.cancel_event = asyncio.Event()


@router.websocket("/stream")
async def stream_completion(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for streaming completions with cancellation support.

    Protocol:
    1. Client connects to /api/stream
    2. Client sends JSON request: {type: "request", model, messages, ...}
    3. Server streams JSON responses: {type: "content"|"done"|"error", content?, ...}
    4. Client can send {type: "cancel"} at any time to stop streaming
    5. Server responds with {type: "cancelled", input_tokens, output_tokens} on cancel
    6. Connection closes after "done", "cancelled", or "error" event
    """
    await websocket.accept()
    logger.info("WebSocket connection accepted")

    state = StreamingState()

    async def listen_for_cancel() -> None:
        """Background task to listen for cancel messages."""
        try:
            while not state.cancelled:
                try:
                    raw_data = await websocket.receive_text()
                    data = json.loads(raw_data)
                    if data.get("type") == "cancel":
                        logger.info("Cancel request received")
                        state.cancelled = True
                        state.cancel_event.set()
                        return
                except (json.JSONDecodeError, WebSocketDisconnect):
                    return
        except Exception:
            # Connection closed or other error
            return

    try:
        # Receive initial request from client
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

        # Validate request type and required fields
        if request.type != "request":
            await websocket.send_json(
                StreamMessage(
                    type="error", error="First message must be type 'request'"
                ).model_dump()
            )
            await websocket.close(code=1003)
            return

        if not request.model or not request.messages:
            await websocket.send_json(
                StreamMessage(
                    type="error", error="'model' and 'messages' are required"
                ).model_dump()
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

        # Start cancel listener in background
        cancel_task = asyncio.create_task(listen_for_cancel())

        # Stream completion
        logger.info(f"Starting stream for {request.model}")
        try:
            async for event in adapter.stream(
                messages=messages,
                model=request.model,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
            ):
                # Check for cancellation before processing each event
                if state.cancelled:
                    logger.info(
                        f"Stream cancelled after {state.output_tokens} output tokens"
                    )
                    await websocket.send_json(
                        StreamMessage(
                            type="cancelled",
                            input_tokens=state.input_tokens,
                            output_tokens=state.output_tokens,
                            finish_reason="cancelled",
                        ).model_dump()
                    )
                    break

                # Track token counts from streaming events
                if event.type == "content":
                    # Count approximate output tokens (will be refined on done)
                    # Rough estimate: ~4 chars per token
                    state.output_tokens += max(1, len(event.content) // 4)

                # Capture final token counts when available
                if event.input_tokens is not None:
                    state.input_tokens = event.input_tokens
                if event.output_tokens is not None:
                    state.output_tokens = event.output_tokens

                message = _event_to_message(event)
                await websocket.send_json(message.model_dump())

                if event.type in ("done", "error"):
                    break
        finally:
            # Clean up cancel listener
            cancel_task.cancel()
            try:
                await cancel_task
            except asyncio.CancelledError:
                pass

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
