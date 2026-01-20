"""OpenAI-compatible API endpoints.

Provides /v1/chat/completions and /v1/models endpoints compatible with
the OpenAI API specification for use with LangChain, AutoGen, and other
OpenAI-compatible tools.

Supports agent:X syntax for agent-based routing:
    model="agent:coder" -> loads agent config, uses agent's primary model
"""

import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
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
from app.constants import (
    CLAUDE_HAIKU,
    CLAUDE_OPUS,
    CLAUDE_SONNET,
    GEMINI_FLASH,
    GEMINI_PRO,
)
from app.db import get_db
from app.services.agent_service import AgentDTO, get_agent_service
from app.services.api_key_auth import AuthenticatedKey, require_api_key

logger = logging.getLogger(__name__)


# Agent prefix for model field
AGENT_PREFIX = "agent:"


@dataclass
class ResolvedModel:
    """Result of model resolution."""

    model: str  # Actual model ID (e.g., "claude-sonnet-4-5")
    provider: str  # Provider name ("claude", "gemini")
    agent: AgentDTO | None = None  # Agent config if resolved from agent:X

router = APIRouter(prefix="/v1", tags=["openai-compat"])

# Model mapping: OpenAI model names -> actual model names
MODEL_MAPPING = {
    # GPT-4 variants -> Claude Sonnet
    "gpt-4": CLAUDE_SONNET,
    "gpt-4-turbo": CLAUDE_SONNET,
    "gpt-4-turbo-preview": CLAUDE_SONNET,
    "gpt-4o": CLAUDE_SONNET,
    "gpt-4o-mini": CLAUDE_HAIKU,
    # GPT-3.5 variants -> Claude Haiku
    "gpt-3.5-turbo": CLAUDE_HAIKU,
    "gpt-3.5-turbo-16k": CLAUDE_HAIKU,
    # Native Claude models (pass through)
    CLAUDE_SONNET: CLAUDE_SONNET,
    CLAUDE_HAIKU: CLAUDE_HAIKU,
    CLAUDE_OPUS: CLAUDE_OPUS,
    # Gemini models
    "gemini-3-flash": GEMINI_FLASH,
    "gemini-3-pro": GEMINI_PRO,
}

# Reverse mapping for display (return original OpenAI-style names)
DISPLAY_MODELS = {
    CLAUDE_SONNET: "gpt-4",
    CLAUDE_HAIKU: "gpt-3.5-turbo",
    CLAUDE_OPUS: "gpt-4-32k",
    GEMINI_FLASH: "gemini-3-flash",
    GEMINI_PRO: "gemini-3-pro",
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


def _resolve_model_sync(model: str) -> tuple[str, str]:
    """Resolve OpenAI model name to actual model and provider (sync version).

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


async def _resolve_model(model: str, db: AsyncSession | None = None) -> ResolvedModel:
    """Resolve model name to actual model, provider, and optional agent config.

    Supports:
    - OpenAI model names (gpt-4 -> claude-sonnet-4-5)
    - Native model names (claude-sonnet-4-5)
    - Agent syntax (agent:coder -> loads agent config)

    Args:
        model: Model identifier (can be "agent:slug" or regular model name)
        db: Database session (required for agent:X resolution)

    Returns:
        ResolvedModel with model, provider, and optional agent config

    Raises:
        HTTPException: If agent not found or db not available for agent:X
    """
    # Check for agent prefix
    if model.startswith(AGENT_PREFIX):
        agent_slug = model[len(AGENT_PREFIX) :]

        if not db:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "message": "Database connection required for agent routing",
                        "type": "internal_error",
                        "code": "db_required",
                    }
                },
            )

        # Load agent config
        service = get_agent_service()
        agent = await service.get_by_slug(db, agent_slug)

        if not agent:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {
                        "message": f"Agent '{agent_slug}' not found",
                        "type": "invalid_request_error",
                        "code": "agent_not_found",
                    }
                },
            )

        # Use agent's primary model
        actual_model = agent.primary_model_id
        logger.info(f"Agent routing: agent:{agent_slug} -> {actual_model}")

        # Determine provider from agent's model
        if "claude" in actual_model.lower():
            provider = "claude"
        elif "gemini" in actual_model.lower():
            provider = "gemini"
        else:
            provider = "claude"

        return ResolvedModel(model=actual_model, provider=provider, agent=agent)

    # Regular model resolution (no agent)
    actual_model, provider = _resolve_model_sync(model)
    return ResolvedModel(model=actual_model, provider=provider, agent=None)


def _get_adapter(provider: str) -> ClaudeAdapter | GeminiAdapter:
    """Get adapter instance for provider."""
    if provider == "claude":
        return ClaudeAdapter()
    elif provider == "gemini":
        return GeminiAdapter()
    raise ValueError(f"Unknown provider: {provider}")


def _get_provider_for_model(model: str) -> str:
    """Determine provider from model name."""
    if "claude" in model.lower():
        return "claude"
    elif "gemini" in model.lower():
        return "gemini"
    return "claude"  # Default


async def _complete_with_fallback(
    messages: list[Message],
    agent: AgentDTO,
    max_tokens: int,
    temperature: float,
) -> tuple[Any, str, bool]:
    """
    Attempt completion with agent's primary model, falling back if needed.

    Args:
        messages: Messages to complete
        agent: Agent config with fallback_models
        max_tokens: Max tokens for completion
        temperature: Temperature for sampling

    Returns:
        Tuple of (result, model_used, used_fallback)
    """
    # Try primary model first
    primary_provider = _get_provider_for_model(agent.primary_model_id)

    try:
        adapter = _get_adapter(primary_provider)
        result = await adapter.complete(
            messages=messages,
            model=agent.primary_model_id,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return result, agent.primary_model_id, False
    except (RateLimitError, ProviderError) as e:
        logger.warning(
            f"Primary model {agent.primary_model_id} failed for agent {agent.slug}: {e}"
        )

    # Try fallback models
    for fallback_model in agent.fallback_models or []:
        fallback_provider = _get_provider_for_model(fallback_model)
        try:
            adapter = _get_adapter(fallback_provider)
            result = await adapter.complete(
                messages=messages,
                model=fallback_model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            logger.info(
                f"Agent {agent.slug} used fallback model: {fallback_model}"
            )
            return result, fallback_model, True
        except (RateLimitError, ProviderError) as e:
            logger.warning(f"Fallback model {fallback_model} also failed: {e}")
            continue

    # All models failed
    raise ProviderError(
        provider=primary_provider,
        message=f"All models failed for agent {agent.slug}: primary={agent.primary_model_id}, "
        f"fallbacks={agent.fallback_models}",
    )


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
    agent: AgentDTO | None = None,
) -> AsyncIterator[str]:
    """Stream chat completion in OpenAI SSE format."""
    adapter = _get_adapter(provider)
    messages = _convert_messages(request.messages)

    # Inject agent's system prompt and mandates if using agent routing
    if agent:
        agent_system_content = agent.system_prompt

        # Inject mandates based on agent's mandate_tags
        if agent.mandate_tags:
            try:
                from app.services.memory import build_agent_mandate_context

                mandate_context, _ = await build_agent_mandate_context(
                    mandate_tags=agent.mandate_tags,
                )
                if mandate_context:
                    agent_system_content = f"{agent_system_content}\n\n---\n\n{mandate_context}"
                    logger.info(f"Injected mandates for streaming agent {agent.slug}")
            except Exception as e:
                logger.warning(f"Failed to inject mandates for streaming agent {agent.slug}: {e}")

        system_idx = next(
            (i for i, m in enumerate(messages) if m.role == "system"),
            None,
        )
        if system_idx is not None:
            messages[system_idx] = Message(
                role="system",
                content=f"{agent_system_content}\n\n---\n\n{messages[system_idx].content}",
            )
        else:
            messages.insert(0, Message(role="system", content=agent_system_content))

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

    # Determine effective temperature and max_tokens (agent config or request)
    effective_temperature = agent.temperature if agent else request.temperature
    effective_max_tokens = request.max_tokens or (agent.max_tokens if agent else 8192)

    try:
        async for event in adapter.stream(
            messages=messages,
            model=actual_model,
            max_tokens=effective_max_tokens,
            temperature=effective_temperature,
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
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
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
    - Agent routing via model="agent:slug" syntax

    Model mapping:
    - gpt-4, gpt-4-turbo, gpt-4o -> claude-sonnet-4-5
    - gpt-4o-mini, gpt-3.5-turbo -> claude-haiku-4-5
    - Native Claude model names also accepted
    - agent:coder, agent:planner, etc -> loads agent config from DB
    """
    # Resolve model (supports agent:X syntax)
    resolved = await _resolve_model(request.model, db)
    actual_model = resolved.model
    provider = resolved.provider
    agent = resolved.agent

    if agent:
        logger.info(
            f"OpenAI compat: {request.model} -> {actual_model} ({provider}) "
            f"[agent: {agent.slug}, temp: {agent.temperature}]"
        )
    else:
        logger.info(f"OpenAI compat: {request.model} -> {actual_model} ({provider})")

    # Determine effective temperature (agent config or request)
    effective_temperature = agent.temperature if agent else request.temperature

    # Handle streaming
    if request.stream:
        return StreamingResponse(
            _stream_completion(request, actual_model, provider, agent),
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

        # Inject agent's system prompt and mandates if using agent routing
        injected_mandate_uuids: list[str] = []
        if agent:
            # Build the agent's full system prompt with mandates
            agent_system_content = agent.system_prompt

            # Inject mandates based on agent's mandate_tags
            if agent.mandate_tags:
                try:
                    from app.services.memory import build_agent_mandate_context

                    mandate_context, injected_mandate_uuids = await build_agent_mandate_context(
                        mandate_tags=agent.mandate_tags,
                    )
                    if mandate_context:
                        # Append mandates to agent's system prompt
                        agent_system_content = f"{agent_system_content}\n\n---\n\n{mandate_context}"
                        logger.info(
                            f"Injected {len(injected_mandate_uuids)} mandates for agent {agent.slug}"
                        )
                except Exception as e:
                    logger.warning(f"Failed to inject mandates for agent {agent.slug}: {e}")

            # Find existing system message or create one
            system_idx = next(
                (i for i, m in enumerate(messages) if m.role == "system"),
                None,
            )
            if system_idx is not None:
                # Prepend agent prompt to existing system message
                messages[system_idx] = Message(
                    role="system",
                    content=f"{agent_system_content}\n\n---\n\n{messages[system_idx].content}",
                )
            else:
                # Insert agent system prompt at the beginning
                messages.insert(0, Message(role="system", content=agent_system_content))

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

        # Determine effective max_tokens
        effective_max_tokens = request.max_tokens or (agent.max_tokens if agent else 8192)

        # Use fallback chain for agent routing, direct call otherwise
        used_fallback = False
        model_used = actual_model
        if agent and agent.fallback_models:
            result, model_used, used_fallback = await _complete_with_fallback(
                messages=messages,
                agent=agent,
                max_tokens=effective_max_tokens,
                temperature=effective_temperature,
            )
            if used_fallback:
                logger.info(f"Agent {agent.slug} used fallback: {model_used}")
        else:
            result = await adapter.complete(
                messages=messages,
                model=actual_model,
                max_tokens=effective_max_tokens,
                temperature=effective_temperature,
            )

        # Log cost for analytics (only for authenticated requests with sessions)
        # Cost logging requires a valid session_id due to FK constraint
        # Anonymous requests don't create sessions, so we skip cost logging for them

        completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        created = int(time.time())
        display_model = DISPLAY_MODELS.get(model_used, request.model)

        response_data = ChatCompletionResponse(
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

        # Build response headers for agent transparency
        headers: dict[str, str] = {}
        if agent:
            headers["X-Agent-Used"] = agent.slug
            headers["X-Model-Used"] = model_used
            if used_fallback:
                headers["X-Fallback-Used"] = "true"
            if injected_mandate_uuids:
                headers["X-Mandates-Injected"] = str(len(injected_mandate_uuids))

        if headers:
            return JSONResponse(
                content=response_data.model_dump(),
                headers=headers,
            )
        return response_data

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
        id=CLAUDE_SONNET,
        created=1715367049,
        owned_by="anthropic",
        context_length=200000,
        supports_vision=True,
        supports_function_calling=True,
    ),
    ModelObject(
        id=CLAUDE_HAIKU,
        created=1715367049,
        owned_by="anthropic",
        context_length=200000,
        supports_vision=True,
        supports_function_calling=True,
    ),
    ModelObject(
        id=CLAUDE_OPUS,
        created=1730419200,
        owned_by="anthropic",
        context_length=200000,
        supports_vision=True,
        supports_function_calling=True,
    ),
    # Gemini models
    ModelObject(
        id=GEMINI_FLASH,
        created=1715367049,
        owned_by="google",
        context_length=1000000,
        supports_vision=True,
        supports_function_calling=True,
    ),
    ModelObject(
        id=GEMINI_PRO,
        created=1715367049,
        owned_by="google",
        context_length=1000000,
        supports_vision=True,
        supports_function_calling=True,
    ),
]


@router.get("/models", response_model=ModelsListResponse)
async def list_models(
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
) -> ModelsListResponse:
    """
    List available models in OpenAI format.

    Returns all models available through Agent Hub with their capabilities.
    """
    return ModelsListResponse(data=AVAILABLE_MODELS)


@router.get("/models/{model_id}", response_model=ModelObject)
async def get_model(
    model_id: str,
    auth: Annotated[AuthenticatedKey | None, Depends(require_api_key)] = None,
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
