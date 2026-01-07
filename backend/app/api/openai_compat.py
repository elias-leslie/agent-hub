"""OpenAI-compatible API endpoints.

Provides /v1/chat/completions and /v1/models endpoints compatible with
the OpenAI API specification for use with LangChain, AutoGen, and other
OpenAI-compatible tools.
"""

import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import (
    AuthenticationError,
    Message,
    ProviderError,
    RateLimitError,
)
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter
from app.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["openai-compat"])

# Model mapping: OpenAI model names -> actual model names
MODEL_MAPPING = {
    # GPT-4 variants -> Claude Sonnet
    "gpt-4": "claude-sonnet-4-5-20250514",
    "gpt-4-turbo": "claude-sonnet-4-5-20250514",
    "gpt-4-turbo-preview": "claude-sonnet-4-5-20250514",
    "gpt-4o": "claude-sonnet-4-5-20250514",
    "gpt-4o-mini": "claude-haiku-4-5-20250514",
    # GPT-3.5 variants -> Claude Haiku
    "gpt-3.5-turbo": "claude-haiku-4-5-20250514",
    "gpt-3.5-turbo-16k": "claude-haiku-4-5-20250514",
    # Native Claude models (pass through)
    "claude-sonnet-4-5": "claude-sonnet-4-5-20250514",
    "claude-haiku-4-5": "claude-haiku-4-5-20250514",
    "claude-opus-4-5": "claude-opus-4-5-20251101",
    # Gemini models
    "gemini-3-flash": "gemini-3-flash-preview",
    "gemini-3-pro": "gemini-3-pro-preview",
}

# Reverse mapping for display
DISPLAY_MODELS = {
    "claude-sonnet-4-5-20250514": "gpt-4",
    "claude-haiku-4-5-20250514": "gpt-3.5-turbo",
    "claude-opus-4-5-20251101": "gpt-4-32k",
    "gemini-3-flash-preview": "gemini-3-flash",
    "gemini-3-pro-preview": "gemini-3-pro",
}


# OpenAI-compatible request/response schemas
class OpenAIFunctionCall(BaseModel):
    """Function call in OpenAI format."""

    name: str
    arguments: str  # JSON string


class OpenAIToolCall(BaseModel):
    """Tool call in OpenAI format."""

    id: str
    type: Literal["function"] = "function"
    function: OpenAIFunctionCall


class OpenAIFunction(BaseModel):
    """Function definition in OpenAI format."""

    name: str
    description: str | None = None
    parameters: dict[str, Any] | None = None


class OpenAITool(BaseModel):
    """Tool definition in OpenAI format."""

    type: Literal["function"] = "function"
    function: OpenAIFunction


class OpenAIMessage(BaseModel):
    """Message in OpenAI format."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    name: str | None = None
    function_call: OpenAIFunctionCall | None = None
    tool_calls: list[OpenAIToolCall] | None = None
    tool_call_id: str | None = None


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request."""

    model: str = Field(..., description="Model to use for completion")
    messages: list[OpenAIMessage] = Field(..., description="Conversation messages")
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    n: int = Field(default=1, ge=1, le=1)  # Only n=1 supported
    stream: bool = Field(default=False)
    stop: str | list[str] | None = None
    max_tokens: int | None = Field(default=None, ge=1)
    presence_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    frequency_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    logit_bias: dict[str, float] | None = None
    user: str | None = None
    tools: list[OpenAITool] | None = None
    tool_choice: str | dict[str, Any] | None = None
    # Deprecated
    functions: list[OpenAIFunction] | None = None
    function_call: str | dict[str, str] | None = None


class ChatCompletionChoice(BaseModel):
    """Choice in OpenAI chat completion response."""

    index: int
    message: OpenAIMessage
    finish_reason: str | None


class ChatCompletionUsage(BaseModel):
    """Usage info in OpenAI format."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    """OpenAI-compatible chat completion response."""

    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: ChatCompletionUsage


class ChatCompletionChunkDelta(BaseModel):
    """Delta in streaming chunk."""

    role: str | None = None
    content: str | None = None
    function_call: OpenAIFunctionCall | None = None
    tool_calls: list[OpenAIToolCall] | None = None


class ChatCompletionChunkChoice(BaseModel):
    """Choice in streaming chunk."""

    index: int
    delta: ChatCompletionChunkDelta
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    """OpenAI-compatible streaming chunk."""

    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChatCompletionChunkChoice]


def _resolve_model(model: str) -> tuple[str, str]:
    """Resolve OpenAI model name to actual model and provider.

    Returns:
        Tuple of (actual_model_name, provider)
    """
    # Check if it's a mapped model
    actual_model = MODEL_MAPPING.get(model, model)

    # Determine provider
    if "claude" in actual_model.lower():
        return actual_model, "claude"
    elif "gemini" in actual_model.lower():
        return actual_model, "gemini"
    else:
        # Default to claude for unknown models
        return actual_model, "claude"


def _get_adapter(provider: str) -> ClaudeAdapter | GeminiAdapter:
    """Get adapter instance for provider."""
    if provider == "claude":
        return ClaudeAdapter()
    elif provider == "gemini":
        return GeminiAdapter()
    raise ValueError(f"Unknown provider: {provider}")


def _convert_messages(messages: list[OpenAIMessage]) -> list[Message]:
    """Convert OpenAI messages to internal Message format."""
    result = []
    for msg in messages:
        # Handle tool/function results
        if msg.role == "tool":
            # Tool results become user messages with context
            content = f"Tool result ({msg.tool_call_id}): {msg.content or ''}"
            result.append(Message(role="user", content=content))
        elif msg.role == "assistant" and msg.tool_calls:
            # Assistant tool calls - format as content
            tool_content = msg.content or ""
            for tc in msg.tool_calls:
                tool_content += f"\n[Tool call: {tc.function.name}({tc.function.arguments})]"
            result.append(Message(role="assistant", content=tool_content.strip()))
        elif msg.role == "assistant" and msg.function_call:
            # Legacy function call
            content = msg.content or ""
            content += f"\n[Function call: {msg.function_call.name}({msg.function_call.arguments})]"
            result.append(Message(role="assistant", content=content.strip()))
        else:
            # Regular message
            role = msg.role if msg.role in ("user", "assistant", "system") else "user"
            result.append(Message(role=role, content=msg.content or ""))  # type: ignore[arg-type]
    return result


def _convert_tools_to_prompt(tools: list[OpenAITool] | None) -> str | None:
    """Convert OpenAI tools to a system prompt addition.

    Claude doesn't use the exact same tool format, so we describe
    available tools in the system prompt for now.
    """
    if not tools:
        return None

    tool_descriptions = []
    for tool in tools:
        func = tool.function
        desc = f"- {func.name}"
        if func.description:
            desc += f": {func.description}"
        if func.parameters:
            desc += f"\n  Parameters: {func.parameters}"
        tool_descriptions.append(desc)

    return "Available tools:\n" + "\n".join(tool_descriptions)


def _map_finish_reason(reason: str | None) -> str:
    """Map provider finish reason to OpenAI format."""
    if reason is None:
        return "stop"
    reason_map = {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "max_tokens": "length",
        "tool_use": "tool_calls",
        "function_call": "function_call",
    }
    return reason_map.get(reason, "stop")


async def _stream_completion(
    request: ChatCompletionRequest,
    actual_model: str,
    provider: str,
) -> AsyncIterator[str]:
    """Stream chat completion in OpenAI SSE format."""
    adapter = _get_adapter(provider)
    messages = _convert_messages(request.messages)

    # Add tool descriptions to system if tools provided
    tool_prompt = _convert_tools_to_prompt(request.tools)
    if tool_prompt:
        # Prepend tool context to first system message or add new one
        if messages and messages[0].role == "system":
            messages[0] = Message(
                role="system",
                content=f"{tool_prompt}\n\n{messages[0].content}",
            )
        else:
            messages.insert(0, Message(role="system", content=tool_prompt))

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    display_model = DISPLAY_MODELS.get(actual_model, request.model)

    # Send initial chunk with role
    initial_chunk = ChatCompletionChunk(
        id=completion_id,
        created=created,
        model=display_model,
        choices=[
            ChatCompletionChunkChoice(
                index=0,
                delta=ChatCompletionChunkDelta(role="assistant"),
                finish_reason=None,
            )
        ],
    )
    yield f"data: {initial_chunk.model_dump_json()}\n\n"

    try:
        async for event in adapter.stream(
            messages=messages,
            model=actual_model,
            max_tokens=request.max_tokens or 4096,
            temperature=request.temperature,
        ):
            if event.type == "content":
                chunk = ChatCompletionChunk(
                    id=completion_id,
                    created=created,
                    model=display_model,
                    choices=[
                        ChatCompletionChunkChoice(
                            index=0,
                            delta=ChatCompletionChunkDelta(content=event.content),
                            finish_reason=None,
                        )
                    ],
                )
                yield f"data: {chunk.model_dump_json()}\n\n"

            elif event.type == "done":
                # Send final chunk with finish reason
                final_chunk = ChatCompletionChunk(
                    id=completion_id,
                    created=created,
                    model=display_model,
                    choices=[
                        ChatCompletionChunkChoice(
                            index=0,
                            delta=ChatCompletionChunkDelta(),
                            finish_reason=_map_finish_reason(event.finish_reason),
                        )
                    ],
                )
                yield f"data: {final_chunk.model_dump_json()}\n\n"

            elif event.type == "error":
                # Send error as a done event
                error_chunk = ChatCompletionChunk(
                    id=completion_id,
                    created=created,
                    model=display_model,
                    choices=[
                        ChatCompletionChunkChoice(
                            index=0,
                            delta=ChatCompletionChunkDelta(content=f"Error: {event.error}"),
                            finish_reason="stop",
                        )
                    ],
                )
                yield f"data: {error_chunk.model_dump_json()}\n\n"

    except Exception as e:
        logger.error(f"Streaming error: {e}")
        error_chunk = ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=display_model,
            choices=[
                ChatCompletionChunkChoice(
                    index=0,
                    delta=ChatCompletionChunkDelta(content=f"Error: {e}"),
                    finish_reason="stop",
                )
            ],
        )
        yield f"data: {error_chunk.model_dump_json()}\n\n"

    yield "data: [DONE]\n\n"


@router.post("/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    request: ChatCompletionRequest,
    authorization: Annotated[str | None, Header()] = None,
    db: Annotated[AsyncSession | None, Depends(get_db)] = None,
) -> ChatCompletionResponse | StreamingResponse:
    """
    OpenAI-compatible chat completions endpoint.

    Maps OpenAI model names to Claude/Gemini models and returns responses
    in OpenAI format for compatibility with existing tools.

    Supports:
    - Standard chat completions
    - Streaming (stream=true)
    - Function/tool definitions (converted to system prompts)

    Model mapping:
    - gpt-4, gpt-4-turbo, gpt-4o -> claude-sonnet-4-5
    - gpt-4o-mini, gpt-3.5-turbo -> claude-haiku-4-5
    - Native Claude model names also accepted
    """
    # Resolve model
    actual_model, provider = _resolve_model(request.model)
    logger.info(f"OpenAI compat: {request.model} -> {actual_model} ({provider})")

    # Handle streaming
    if request.stream:
        return StreamingResponse(
            _stream_completion(request, actual_model, provider),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Non-streaming completion
    try:
        adapter = _get_adapter(provider)
        messages = _convert_messages(request.messages)

        # Add tool descriptions to system if tools provided
        tool_prompt = _convert_tools_to_prompt(request.tools)
        if tool_prompt:
            if messages and messages[0].role == "system":
                messages[0] = Message(
                    role="system",
                    content=f"{tool_prompt}\n\n{messages[0].content}",
                )
            else:
                messages.insert(0, Message(role="system", content=tool_prompt))

        result = await adapter.complete(
            messages=messages,
            model=actual_model,
            max_tokens=request.max_tokens or 4096,
            temperature=request.temperature,
        )

        completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        created = int(time.time())
        display_model = DISPLAY_MODELS.get(actual_model, request.model)

        return ChatCompletionResponse(
            id=completion_id,
            created=created,
            model=display_model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=OpenAIMessage(
                        role="assistant",
                        content=result.content,
                    ),
                    finish_reason=_map_finish_reason(result.finish_reason),
                )
            ],
            usage=ChatCompletionUsage(
                prompt_tokens=result.input_tokens,
                completion_tokens=result.output_tokens,
                total_tokens=result.input_tokens + result.output_tokens,
            ),
        )

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e

    except RateLimitError as e:
        logger.warning(f"Rate limit for {e.provider}")
        raise HTTPException(
            status_code=429,
            detail={
                "error": {
                    "message": f"Rate limit exceeded for {e.provider}",
                    "type": "rate_limit_error",
                    "code": "rate_limit_exceeded",
                }
            },
            headers={"Retry-After": str(int(e.retry_after)) if e.retry_after else "60"},
        ) from e

    except AuthenticationError as e:
        logger.error(f"Auth error for {e.provider}")
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": f"Authentication failed for {e.provider}",
                    "type": "authentication_error",
                    "code": "invalid_api_key",
                }
            },
        ) from e

    except ProviderError as e:
        logger.error(f"Provider error: {e}")
        status_code = e.status_code or 500
        raise HTTPException(
            status_code=status_code,
            detail={
                "error": {
                    "message": str(e),
                    "type": "api_error",
                    "code": "provider_error",
                }
            },
        ) from e

    except Exception as e:
        logger.exception(f"Unexpected error in chat/completions: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": {
                    "message": "Internal server error",
                    "type": "internal_error",
                    "code": "internal_error",
                }
            },
        ) from e


# Models endpoint schemas
class ModelObject(BaseModel):
    """Model object in OpenAI format."""

    id: str
    object: Literal["model"] = "model"
    created: int
    owned_by: str
    # Extended fields
    context_length: int | None = None
    supports_vision: bool = False
    supports_function_calling: bool = True


class ModelsListResponse(BaseModel):
    """List models response in OpenAI format."""

    object: Literal["list"] = "list"
    data: list[ModelObject]


# Available models with metadata
AVAILABLE_MODELS = [
    ModelObject(
        id="gpt-4",
        created=1687882411,
        owned_by="agent-hub",
        context_length=200000,
        supports_vision=True,
        supports_function_calling=True,
    ),
    ModelObject(
        id="gpt-4-turbo",
        created=1706037612,
        owned_by="agent-hub",
        context_length=200000,
        supports_vision=True,
        supports_function_calling=True,
    ),
    ModelObject(
        id="gpt-4o",
        created=1715367049,
        owned_by="agent-hub",
        context_length=200000,
        supports_vision=True,
        supports_function_calling=True,
    ),
    ModelObject(
        id="gpt-4o-mini",
        created=1721172741,
        owned_by="agent-hub",
        context_length=200000,
        supports_vision=True,
        supports_function_calling=True,
    ),
    ModelObject(
        id="gpt-3.5-turbo",
        created=1677610602,
        owned_by="agent-hub",
        context_length=200000,
        supports_vision=False,
        supports_function_calling=True,
    ),
    # Native Claude models
    ModelObject(
        id="claude-sonnet-4-5",
        created=1715367049,
        owned_by="anthropic",
        context_length=200000,
        supports_vision=True,
        supports_function_calling=True,
    ),
    ModelObject(
        id="claude-haiku-4-5",
        created=1715367049,
        owned_by="anthropic",
        context_length=200000,
        supports_vision=True,
        supports_function_calling=True,
    ),
    ModelObject(
        id="claude-opus-4-5",
        created=1730419200,
        owned_by="anthropic",
        context_length=200000,
        supports_vision=True,
        supports_function_calling=True,
    ),
    # Gemini models
    ModelObject(
        id="gemini-3-flash",
        created=1715367049,
        owned_by="google",
        context_length=1000000,
        supports_vision=True,
        supports_function_calling=True,
    ),
    ModelObject(
        id="gemini-3-pro",
        created=1715367049,
        owned_by="google",
        context_length=1000000,
        supports_vision=True,
        supports_function_calling=True,
    ),
]


@router.get("/models", response_model=ModelsListResponse)
async def list_models(
    authorization: Annotated[str | None, Header()] = None,
) -> ModelsListResponse:
    """
    List available models in OpenAI format.

    Returns all models available through Agent Hub with their capabilities.
    """
    return ModelsListResponse(data=AVAILABLE_MODELS)


@router.get("/models/{model_id}", response_model=ModelObject)
async def get_model(
    model_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> ModelObject:
    """
    Get a specific model's details.
    """
    for model in AVAILABLE_MODELS:
        if model.id == model_id:
            return model
    raise HTTPException(
        status_code=404,
        detail={
            "error": {
                "message": f"Model '{model_id}' not found",
                "type": "invalid_request_error",
                "code": "model_not_found",
            }
        },
    )
