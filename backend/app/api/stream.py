"""WebSocket streaming API for real-time completions."""

import asyncio
import contextlib
import json
import logging
import os
import uuid
from typing import Literal

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError

from app.adapters.base import Message, StreamEvent
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter
from app.constants import OUTPUT_LIMIT_CHAT
from app.services.events import (
    publish_complete,
    publish_error,
    publish_message,
    publish_session_start,
)
from app.services.stream_registry import get_stream_registry
from app.services.token_counter import validate_max_tokens

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
    max_tokens: int = Field(default=OUTPUT_LIMIT_CHAT, ge=1, le=100000)
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)
    session_id: str | None = Field(default=None, description="Optional session ID")
    working_dir: str | None = Field(
        default=None, description="Working directory for tool execution"
    )
    tools_enabled: bool = Field(
        default=False, description="Enable tool calling for coding agent mode"
    )


class StreamMessage(BaseModel):
    """Message sent to client during streaming."""

    type: str = Field(
        ..., description="Event type: content, done, cancelled, tool_use, tool_result, or error"
    )
    content: str = Field(default="", description="Content chunk for 'content' events")
    input_tokens: int | None = Field(
        default=None, description="Input tokens (on 'done'/'cancelled')"
    )
    output_tokens: int | None = Field(
        default=None, description="Output tokens (on 'done'/'cancelled')"
    )
    finish_reason: str | None = Field(default=None, description="Why generation stopped")
    error: str | None = Field(default=None, description="Error message for 'error' events")
    # Output usage fields (on 'done')
    max_tokens_requested: int | None = Field(
        default=None, description="max_tokens used for request"
    )
    model_limit: int | None = Field(default=None, description="Model's max output capability")
    was_truncated: bool | None = Field(
        default=None, description="True if truncated (finish_reason=max_tokens)"
    )
    truncation_warning: str | None = Field(
        default=None, description="Warning if truncated or capped"
    )
    # Tool use fields
    tool_name: str | None = Field(default=None, description="Tool name for tool_use events")
    tool_input: dict | None = Field(default=None, description="Tool input for tool_use events")
    tool_id: str | None = Field(default=None, description="Tool call ID for tool_use events")
    tool_result: str | None = Field(default=None, description="Tool output for tool_result events")
    tool_status: str | None = Field(
        default=None, description="Tool status: running, complete, error"
    )


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


def _parse_sdk_message(message: object) -> list[StreamMessage]:
    """Parse Claude SDK message into StreamMessage events.

    The SDK yields various message types during the agentic loop:
    - init: System initialization with session_id
    - assistant: Model response with text/tool_use content blocks
    - tool_result: Result from tool execution
    - result: Final result (success/error)
    - error: Error during execution

    Reference: automaker/apps/server/src/services/agent-service.ts:401-508
    """
    events: list[StreamMessage] = []

    # Get message type and subtype
    msg_type = getattr(message, "type", None)
    msg_subtype = getattr(message, "subtype", None)

    if msg_type == "assistant":
        # Assistant messages contain content blocks (text, tool_use)
        msg_content = getattr(message, "message", None)
        if msg_content and hasattr(msg_content, "content"):
            for block in msg_content.content:
                block_type = getattr(block, "type", None)
                if block_type == "text":
                    # Text content - stream as content event
                    text = getattr(block, "text", "")
                    if text:
                        events.append(StreamMessage(type="content", content=text))
                elif block_type == "tool_use":
                    # Tool use - extract name and input
                    tool_name = getattr(block, "name", "unknown")
                    tool_input = getattr(block, "input", {})
                    tool_id = getattr(block, "id", str(uuid.uuid4()))
                    events.append(
                        StreamMessage(
                            type="tool_use",
                            tool_name=tool_name,
                            tool_input=tool_input if isinstance(tool_input, dict) else {},
                            tool_id=tool_id,
                            tool_status="running",
                        )
                    )

    elif msg_type == "tool_result" or msg_subtype == "tool_result":
        # Tool result from execution
        result_content = getattr(message, "content", "")
        tool_id = getattr(message, "tool_use_id", None)
        is_error = getattr(message, "is_error", False)
        events.append(
            StreamMessage(
                type="tool_result",
                tool_id=tool_id,
                tool_result=str(result_content) if result_content else "",
                tool_status="error" if is_error else "complete",
            )
        )

    elif msg_type == "result":
        # Final result
        if msg_subtype == "success":
            result_text = getattr(message, "result", "")
            events.append(
                StreamMessage(
                    type="done",
                    content=result_text or "",
                    finish_reason="stop",
                )
            )
        elif msg_subtype == "error":
            error_msg = getattr(message, "error", "Unknown error")
            events.append(StreamMessage(type="error", error=str(error_msg)))

    elif msg_type == "error":
        error_msg = getattr(message, "error", "Unknown error")
        events.append(StreamMessage(type="error", error=str(error_msg)))

    return events


class StreamingState:
    """State for an active streaming session."""

    def __init__(self) -> None:
        self.cancelled = False
        self.input_tokens = 0
        self.output_tokens = 0
        self.cancel_event = asyncio.Event()
        self.accumulated_content = ""  # For event publishing on done
        # Output usage tracking
        self.effective_max_tokens = 0
        self.model_limit = 0
        self.validation_warning: str | None = None


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

        # Validate working_dir if provided (for tool-enabled mode)
        if request.working_dir:
            if not os.path.isabs(request.working_dir):
                await websocket.send_json(
                    StreamMessage(
                        type="error", error="working_dir must be an absolute path"
                    ).model_dump()
                )
                await websocket.close(code=1003)
                return
            if not os.path.isdir(request.working_dir):
                await websocket.send_json(
                    StreamMessage(
                        type="error", error=f"working_dir does not exist: {request.working_dir}"
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
            await websocket.send_json(StreamMessage(type="error", error=str(e)).model_dump())
            await websocket.close(code=1003)
            return

        # Convert messages
        messages = [
            Message(role=m.get("role", "user"), content=m.get("content", ""))  # type: ignore[arg-type]
            for m in request.messages
        ]

        # Validate max_tokens against model output limit
        max_tokens_validation = validate_max_tokens(request.model, request.max_tokens)
        state.effective_max_tokens = max_tokens_validation.effective_max_tokens
        state.model_limit = max_tokens_validation.model_limit
        state.validation_warning = max_tokens_validation.warning
        if max_tokens_validation.warning:
            logger.warning(
                f"max_tokens capped for {request.model}: {request.max_tokens} -> {state.effective_max_tokens}"
            )

        # Register stream in registry for REST cancellation
        await registry.register_stream(session_id, request.model)

        # Publish session_start event
        await publish_session_start(session_id, request.model)

        # Start cancel listeners in background
        ws_cancel_task = asyncio.create_task(listen_for_cancel())
        registry_cancel_task = asyncio.create_task(poll_registry_cancel())

        # Stream completion
        logger.info(f"Starting stream for {request.model} (session: {session_id})")

        # Determine if we should use tool-enabled mode
        use_claude_tools = (
            request.tools_enabled and provider == "claude" and isinstance(adapter, ClaudeAdapter)
        )
        use_gemini_tools = (
            request.tools_enabled and provider == "gemini" and isinstance(adapter, GeminiAdapter)
        )
        use_tools = use_claude_tools or use_gemini_tools

        if use_tools:
            logger.info(
                f"Tool-enabled mode ({provider}): working_dir={request.working_dir}, model={request.model}"
            )

        try:
            # Choose streaming path based on tool mode
            if use_tools:
                # Tool-enabled path using adapter's complete_with_tools
                # Define minimal tool set for coding agent
                tools = [
                    {
                        "name": "Read",
                        "description": "Read file contents",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "file_path": {"type": "string", "description": "Path to file"},
                            },
                            "required": ["file_path"],
                        },
                    },
                    {
                        "name": "Write",
                        "description": "Write content to file",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "file_path": {"type": "string", "description": "Path to file"},
                                "content": {"type": "string", "description": "Content to write"},
                            },
                            "required": ["file_path", "content"],
                        },
                    },
                    {
                        "name": "Bash",
                        "description": "Execute bash command",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "command": {"type": "string", "description": "Command to run"},
                            },
                            "required": ["command"],
                        },
                    },
                ]

                # Create the appropriate tool-enabled generator
                if use_claude_tools:
                    claude_adapter = adapter  # type: ClaudeAdapter
                    tool_generator = claude_adapter.complete_with_tools(
                        messages=messages,
                        model=request.model,
                        tools=tools,
                        write_enabled=True,
                        yolo_mode=False,
                        working_dir=request.working_dir,
                        max_tokens=state.effective_max_tokens,
                    )
                else:  # Gemini
                    gemini_adapter = adapter  # type: GeminiAdapter
                    tool_generator = gemini_adapter.complete_with_tools(
                        messages=messages,
                        model=request.model,
                        tools=tools,
                        working_dir=request.working_dir,
                        max_tokens=state.effective_max_tokens,
                    )

                async for sdk_message, _sdk_session_id in tool_generator:
                    # Check for cancellation
                    if state.cancelled:
                        logger.info(f"Stream cancelled after {state.output_tokens} output tokens")
                        await publish_error(session_id, "StreamCancelled", "User cancelled stream")
                        await websocket.send_json(
                            StreamMessage(
                                type="cancelled",
                                input_tokens=state.input_tokens,
                                output_tokens=state.output_tokens,
                                finish_reason="cancelled",
                            ).model_dump()
                        )
                        break

                    # Parse SDK message into StreamMessage events
                    stream_events = _parse_sdk_message(sdk_message)
                    for stream_msg in stream_events:
                        # Track content for token estimation
                        if stream_msg.type == "content" and stream_msg.content:
                            state.output_tokens += max(1, len(stream_msg.content) // 4)
                            state.accumulated_content += stream_msg.content

                        # Send event to client
                        await websocket.send_json(stream_msg.model_dump())

                        # Handle completion
                        if stream_msg.type == "done":
                            if state.accumulated_content:
                                await publish_message(
                                    session_id,
                                    "assistant",
                                    state.accumulated_content,
                                    state.output_tokens,
                                )
                            await publish_complete(
                                session_id, state.input_tokens, state.output_tokens
                            )

                        # Handle errors
                        if stream_msg.type == "error":
                            await publish_error(
                                session_id, "StreamError", stream_msg.error or "Unknown error"
                            )

            else:
                # Standard streaming path (no tools)
                async for event in adapter.stream(
                    messages=messages,
                    model=request.model,
                    max_tokens=state.effective_max_tokens,  # Use validated/capped value
                    temperature=request.temperature,
                ):
                    # Check for cancellation before processing each event
                    if state.cancelled:
                        logger.info(f"Stream cancelled after {state.output_tokens} output tokens")
                        # Publish cancellation as error event
                        await publish_error(session_id, "StreamCancelled", "User cancelled stream")
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
                        # Accumulate content for final message event
                        state.accumulated_content += event.content

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

                    # Handle done event specially to include output usage info
                    if event.type == "done":
                        # Check for truncation - handle different provider formats
                        finish_lower = (event.finish_reason or "").lower()
                        was_truncated = "max_tokens" in finish_lower
                        truncation_warning = state.validation_warning
                        if was_truncated and not truncation_warning:
                            truncation_warning = f"Response truncated at {state.output_tokens} tokens (max_tokens limit reached)."

                        done_message = StreamMessage(
                            type="done",
                            content=event.content,
                            input_tokens=event.input_tokens or state.input_tokens,
                            output_tokens=event.output_tokens or state.output_tokens,
                            finish_reason=event.finish_reason,
                            max_tokens_requested=state.effective_max_tokens,
                            model_limit=state.model_limit,
                            was_truncated=was_truncated,
                            truncation_warning=truncation_warning,
                        )
                        await websocket.send_json(done_message.model_dump())

                        # Publish accumulated assistant message
                        if state.accumulated_content:
                            await publish_message(
                                session_id,
                                "assistant",
                                state.accumulated_content,
                                state.output_tokens,
                            )
                        # Publish complete event
                        await publish_complete(session_id, state.input_tokens, state.output_tokens)

                        if was_truncated:
                            logger.info(
                                f"Stream truncated: model={request.model}, "
                                f"tokens={state.output_tokens}/{state.effective_max_tokens}"
                            )
                        break

                    message = _event_to_message(event)
                    await websocket.send_json(message.model_dump())

                    # Publish events on error
                    if event.type == "error":
                        await publish_error(
                            session_id, "StreamError", event.error or "Unknown error"
                        )
                        break
        finally:
            # Clean up cancel listeners
            ws_cancel_task.cancel()
            registry_cancel_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ws_cancel_task
            with contextlib.suppress(asyncio.CancelledError):
                await registry_cancel_task
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
        # Publish error event
        if session_id:
            await publish_error(session_id, "UnexpectedError", str(e))
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
