"""WebSocket streaming API for real-time completions."""

import asyncio
import contextlib
import json
import logging
import os
import uuid
from typing import Any, Literal

import jsonschema
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
from app.services.memory import inject_memory_context, parse_memory_group_id
from app.services.memory.episode_creator import get_episode_creator
from app.services.memory.ingestion_config import CHAT_STREAM
from app.services.memory.service import MemorySource
from app.services.stream_registry import get_stream_registry
from app.services.token_counter import get_output_limit

logger = logging.getLogger(__name__)

router = APIRouter()


class ResponseFormat(BaseModel):
    """Response format specification for structured output (JSON mode)."""

    type: str = Field(
        default="text",
        description="Output type: 'text' (default) or 'json_object' for JSON mode",
    )
    schema_: dict | None = Field(
        default=None,
        alias="schema",
        description="JSON Schema for validating structured output (optional)",
    )

    model_config = {"populate_by_name": True}


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
    response_format: ResponseFormat | None = Field(
        default=None,
        description="Response format: {type: 'json_object', schema: {...}} for JSON mode",
    )
    # Memory options
    use_memory: bool = Field(
        default=False,
        description="Inject relevant context from knowledge graph memory",
    )
    memory_group_id: str | None = Field(
        default=None,
        description="Memory group ID for isolation (defaults to session_id)",
    )
    store_as_episode: bool = Field(
        default=False,
        description="Store conversation as memory episode on completion",
    )
    project_id: str | None = Field(
        default=None,
        description="Project ID for memory grouping (used if memory_group_id not set)",
    )
    # Agent routing (unified API)
    agent_slug: str | None = Field(
        default=None,
        description="Agent slug for routing (e.g., 'coder'). Injects mandates and uses fallbacks.",
    )


class StreamMessage(BaseModel):
    """Message sent to client during streaming."""

    type: str = Field(
        ...,
        description="Event type: content, done, cancelled, tool_use, tool_result, connected, or error",
    )
    content: str = Field(default="", description="Content chunk for 'content' events")
    # Session tracking (on 'connected'/'done'/'cancelled')
    session_id: str | None = Field(default=None, description="Session ID for tracking")
    # Provider info (on 'done'/'cancelled')
    provider: str | None = Field(default=None, description="Provider: 'claude' or 'gemini'")
    model: str | None = Field(default=None, description="Model identifier used")
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
    # Structured output fields (on 'done' when JSON mode)
    parsed_json: dict | None = Field(
        default=None, description="Parsed JSON when response_format type is 'json_object'"
    )
    # Tool use fields
    tool_name: str | None = Field(default=None, description="Tool name for tool_use events")
    tool_input: dict | None = Field(default=None, description="Tool input for tool_use events")
    tool_id: str | None = Field(default=None, description="Tool call ID for tool_use events")
    tool_result: str | None = Field(default=None, description="Tool output for tool_result events")
    tool_status: str | None = Field(
        default=None, description="Tool status: running, complete, error"
    )
    # Memory fields
    memory_facts_injected: int | None = Field(
        default=None, description="Number of memory facts injected (on 'connected')"
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
    # Note: SDK messages may have type=None, use class name as fallback
    msg_type = getattr(message, "type", None)
    msg_subtype = getattr(message, "subtype", None)
    msg_class = type(message).__name__

    # Log message type for debugging (debug level)
    logger.debug(f"SDK message: type={msg_type}, subtype={msg_subtype}, class={msg_class}")

    if msg_type == "assistant" or msg_class == "AssistantMessage":
        # Assistant messages contain content blocks (text, tool_use)
        # SDK may put content in 'message' attribute or directly on object
        msg_content = getattr(message, "message", None) or message
        if msg_content and hasattr(msg_content, "content"):
            for block in msg_content.content:
                block_class = type(block).__name__
                block_type = getattr(block, "type", None)

                # Handle TextBlock (type="text" or class name)
                if block_type == "text" or block_class == "TextBlock":
                    text = getattr(block, "text", "")
                    if text:
                        events.append(StreamMessage(type="content", content=text))

                # Handle ToolUseBlock (type="tool_use" or class name)
                elif block_type == "tool_use" or block_class == "ToolUseBlock":
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

    elif (
        msg_type == "tool_result"
        or msg_subtype == "tool_result"
        or msg_class == "ToolResultMessage"
    ):
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

    elif msg_class == "UserMessage":
        # UserMessage may contain tool results (ToolResultBlock)
        user_content = getattr(message, "content", [])
        if user_content:
            for block in user_content:
                block_class = type(block).__name__
                if block_class == "ToolResultBlock":
                    tool_id = getattr(block, "tool_use_id", None)
                    result_content = getattr(block, "content", "")
                    is_error = getattr(block, "is_error", False)
                    events.append(
                        StreamMessage(
                            type="tool_result",
                            tool_id=tool_id,
                            tool_result=str(result_content) if result_content else "",
                            tool_status="error" if is_error else "complete",
                        )
                    )

    elif msg_type == "result" or msg_class == "ResultMessage":
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


def validate_json_response(
    content: str, schema: dict[str, Any]
) -> tuple[bool, str | None, dict | None]:
    """Validate JSON response against a JSON Schema.

    Args:
        content: The response content (should be valid JSON).
        schema: The JSON Schema to validate against.

    Returns:
        Tuple of (is_valid, error_message, parsed_dict). If valid, error_message is None.
    """
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}", None

    try:
        jsonschema.validate(instance=parsed, schema=schema)
        return True, None, parsed
    except jsonschema.ValidationError as e:
        return False, f"Schema validation failed: {e.message}", None


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
        # JSON mode tracking
        self.json_mode_enabled = False
        self.json_schema: dict[str, Any] | None = None
        # Memory tracking
        self.memory_facts_injected = 0
        self.memory_group_id: str | None = None
        self.store_as_episode = False
        self.original_user_message = ""  # For episode storage


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

        # Agent routing (limited support in WebSocket - full support via SSE /api/complete)
        resolved_model = request.model
        if request.agent_slug:
            logger.warning(
                f"agent_slug '{request.agent_slug}' provided to WebSocket stream. "
                "Full agent routing (mandates, fallbacks) requires SSE via POST /api/complete?stream=true. "
                "WebSocket will use the provided model without agent-specific routing."
            )

        # Get provider and adapter
        provider = _get_provider(resolved_model)
        try:
            adapter = _get_adapter(provider)
        except ValueError as e:
            await websocket.send_json(StreamMessage(type="error", error=str(e)).model_dump())
            await websocket.close(code=1003)
            return

        # Convert messages to dict format for memory injection
        messages_dict = [
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in request.messages
        ]

        # Store original user message for episode storage
        for msg in reversed(messages_dict):
            if msg.get("role") == "user":
                state.original_user_message = msg.get("content", "")
                break

        # Inject memory context if enabled
        state.memory_group_id = request.memory_group_id or request.project_id or session_id
        state.store_as_episode = request.store_as_episode
        if request.use_memory:
            scope, scope_id = parse_memory_group_id(request.memory_group_id)
            try:
                messages_dict, state.memory_facts_injected = await inject_memory_context(
                    messages=messages_dict,
                    scope=scope,
                    scope_id=scope_id,
                )
                if state.memory_facts_injected > 0:
                    logger.info(
                        f"Injected {state.memory_facts_injected} memory facts for stream "
                        f"(session={session_id}, scope={scope.value})"
                    )
            except Exception as e:
                logger.warning(f"Memory injection failed (continuing without): {e}")

        # Convert to adapter Message format
        messages = [
            Message(role=m.get("role", "user"), content=m.get("content", ""))  # type: ignore[arg-type]
            for m in messages_dict
        ]

        # Pass through max_tokens directly - no capping
        state.effective_max_tokens = request.max_tokens
        state.model_limit = get_output_limit(request.model)
        state.validation_warning = None

        # Set up JSON mode if requested
        if request.response_format and request.response_format.type == "json_object":
            state.json_mode_enabled = True
            state.json_schema = request.response_format.schema_
            logger.info("Streaming with JSON mode enabled")

        # Register stream in registry for REST cancellation
        await registry.register_stream(session_id, request.model)

        # Publish session_start event
        await publish_session_start(session_id, request.model)

        # Send connected event with session_id to client
        connected_message = StreamMessage(
            type="connected",
            session_id=session_id,
            model=request.model,
            provider=provider,
            memory_facts_injected=state.memory_facts_injected if request.use_memory else None,
        )
        await websocket.send_json(connected_message.model_dump())

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
                                session_id=session_id,
                                provider=provider,
                                model=request.model,
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
                            # Store conversation as memory episode if requested
                            if state.store_as_episode and state.accumulated_content:
                                try:
                                    from graphiti_core.utils.datetime_utils import utc_now

                                    episode_content = (
                                        f"User: {state.original_user_message}\n"
                                        f"Assistant: {state.accumulated_content}"
                                    )
                                    creator = get_episode_creator(
                                        scope_id=state.memory_group_id or session_id
                                    )
                                    result = await creator.create(
                                        content=episode_content,
                                        name=f"chat_{utc_now().strftime('%Y%m%d_%H%M%S')}",
                                        config=CHAT_STREAM,
                                        source_description="tool-enabled stream conversation",
                                        source=MemorySource.CHAT,
                                    )
                                    if result.success:
                                        logger.info(
                                            f"Stored tool stream conversation as episode {result.uuid}"
                                        )
                                except Exception as e:
                                    logger.warning(f"Failed to store tool stream episode: {e}")

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
                    max_tokens=state.effective_max_tokens,
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
                                session_id=session_id,
                                provider=provider,
                                model=request.model,
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

                        # Handle JSON mode validation
                        parsed_json = None
                        if state.json_mode_enabled and state.json_schema:
                            is_valid, validation_error, parsed_json = validate_json_response(
                                state.accumulated_content, state.json_schema
                            )
                            if not is_valid:
                                # Send error event instead of done
                                error_message = StreamMessage(
                                    type="error",
                                    error=f"JSON validation failed: {validation_error}",
                                )
                                await websocket.send_json(error_message.model_dump())
                                await publish_error(
                                    session_id,
                                    "JSONValidationError",
                                    validation_error or "Unknown validation error",
                                )
                                break

                        done_message = StreamMessage(
                            type="done",
                            session_id=session_id,
                            content=event.content,
                            provider=provider,
                            model=request.model,
                            input_tokens=event.input_tokens or state.input_tokens,
                            output_tokens=event.output_tokens or state.output_tokens,
                            finish_reason=event.finish_reason,
                            max_tokens_requested=state.effective_max_tokens,
                            model_limit=state.model_limit,
                            was_truncated=was_truncated,
                            truncation_warning=truncation_warning,
                            parsed_json=parsed_json,
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

                        # Store conversation as memory episode if requested
                        if state.store_as_episode and state.accumulated_content:
                            try:
                                from graphiti_core.utils.datetime_utils import utc_now

                                episode_content = (
                                    f"User: {state.original_user_message}\n"
                                    f"Assistant: {state.accumulated_content}"
                                )
                                creator = get_episode_creator(
                                    scope_id=state.memory_group_id or session_id
                                )
                                result = await creator.create(
                                    content=episode_content,
                                    name=f"chat_{utc_now().strftime('%Y%m%d_%H%M%S')}",
                                    config=CHAT_STREAM,
                                    source_description="stream conversation",
                                    source=MemorySource.CHAT,
                                )
                                if result.success:
                                    logger.info(f"Stored stream conversation as episode {result.uuid}")
                            except Exception as e:
                                logger.warning(f"Failed to store stream episode: {e}")

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
