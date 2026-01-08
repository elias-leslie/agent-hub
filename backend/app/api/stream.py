"""WebSocket streaming API for real-time completions."""

import asyncio
import json
import logging
import uuid
from typing import Any, Literal

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError

from app.adapters.base import Message, StreamEvent
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter
from app.services.stream_registry import get_stream_registry

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


# Cached adapter instances - created once, reused across requests
_adapter_cache: dict[str, ClaudeAdapter | GeminiAdapter] = {}


def _get_adapter(provider: str) -> ClaudeAdapter | GeminiAdapter:
    """Get cached adapter instance for provider."""
    if provider in _adapter_cache:
        return _adapter_cache[provider]

    if provider == "claude":
        adapter: ClaudeAdapter | GeminiAdapter = ClaudeAdapter()
    elif provider == "gemini":
        adapter = GeminiAdapter()
    else:
        raise ValueError(f"Unknown provider: {provider}")

    _adapter_cache[provider] = adapter
    logger.info(f"Created cached adapter for {provider}")
    return adapter


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
    5. Server can also be cancelled via REST POST /sessions/{id}/cancel
    6. Server responds with {type: "cancelled", input_tokens, output_tokens} on cancel
    7. Connection closes after "done", "cancelled", or "error" event
    """
    await websocket.accept()
    logger.info("WebSocket connection accepted")

    state = StreamingState()
    registry = get_stream_registry()
    session_id: str | None = None

    async def listen_for_cancel() -> None:
        """Background task to listen for cancel messages via WebSocket."""
        try:
            while not state.cancelled:
                try:
                    raw_data = await websocket.receive_text()
                    data = json.loads(raw_data)
                    if data.get("type") == "cancel":
                        logger.info("Cancel request received via WebSocket")
                        state.cancelled = True
                        state.cancel_event.set()
                        return
                except (json.JSONDecodeError, WebSocketDisconnect):
                    return
        except Exception as e:
            # Connection closed or other error - expected during cleanup
            logger.debug(f"Cancel listener exited: {e}")
            return

    async def poll_registry_cancel() -> None:
        """Background task to check registry for REST-initiated cancellation."""
        try:
            while not state.cancelled and session_id:
                if await registry.is_cancelled(session_id):
                    logger.info(f"Cancel detected via registry for {session_id}")
                    state.cancelled = True
                    state.cancel_event.set()
                    return
                await asyncio.sleep(0.1)  # Check every 100ms
        except Exception as e:
            # Registry poll error - expected during cleanup
            logger.debug(f"Registry poll exited: {e}")
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

        # Use provided session_id or generate one for tracking
        session_id = request.session_id or str(uuid.uuid4())

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

        # Register stream in registry for REST cancellation
        await registry.register_stream(session_id, request.model)

        # Start cancel listeners in background
        ws_cancel_task = asyncio.create_task(listen_for_cancel())
        registry_cancel_task = asyncio.create_task(poll_registry_cancel())

        # Stream completion
        logger.info(f"Starting stream for {request.model} (session: {session_id})")
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

                # Update registry with current token counts periodically
                if event.type == "content" and state.output_tokens % 100 < 10:
                    await registry.update_tokens(
                        session_id, state.input_tokens, state.output_tokens
                    )

                message = _event_to_message(event)
                await websocket.send_json(message.model_dump())

                if event.type in ("done", "error"):
                    break
        finally:
            # Clean up cancel listeners
            ws_cancel_task.cancel()
            registry_cancel_task.cancel()
            try:
                await ws_cancel_task
            except asyncio.CancelledError:
                pass
            try:
                await registry_cancel_task
            except asyncio.CancelledError:
                pass
            # Unregister from registry
            if session_id:
                await registry.unregister_stream(session_id)

        logger.info("Stream completed, closing connection")
        await websocket.close(code=1000)

    except WebSocketDisconnect:
        logger.info("Client disconnected")
        # Unregister from registry on disconnect
        if session_id:
            await registry.unregister_stream(session_id)

    except Exception as e:
        logger.exception(f"Unexpected error in stream: {e}")
        # Unregister from registry on error
        if session_id:
            await registry.unregister_stream(session_id)
        try:
            await websocket.send_json(
                StreamMessage(type="error", error=f"Internal error: {e}").model_dump()
            )
            await websocket.close(code=1011)
        except Exception as cleanup_err:
            # WebSocket might be closed already - log and ignore
            logger.debug(f"Error during cleanup: {cleanup_err}")
