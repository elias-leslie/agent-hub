"""Completion API endpoint."""

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.adapters.base import (
    AuthenticationError,
    CompletionResult,
    Message,
    ProviderError,
    RateLimitError,
)
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter
from app.db import get_db
from app.models import Message as DBMessage
from app.models import Session as DBSession

# NOTE: Auto-compression removed per Anthropic harness architecture guidance.
# Context management belongs in the harness (SummitFlow), not the API layer.
# Agent Hub provides token tracking and warnings; the caller decides when to
# checkpoint and restart. See: anthropic.com/engineering/effective-harnesses-for-long-running-agents
from app.services.context_tracker import (
    check_context_before_request,
    log_token_usage,
    should_emit_warning,
)
from app.services.response_cache import get_response_cache
from app.services.token_counter import count_message_tokens, estimate_cost, estimate_request

logger = logging.getLogger(__name__)

router = APIRouter()


# Request/Response schemas
class MessageInput(BaseModel):
    """Input message in conversation.

    Content can be:
    - str: Simple text content
    - list[dict]: Content blocks for vision (text + image)

    Image block format:
    {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": "<base64-encoded-data>"
        }
    }
    """

    role: str = Field(..., description="Message role: user, assistant, or system")
    content: str | list[dict[str, Any]] = Field(
        ..., description="Message content - string or list of content blocks"
    )


class ToolDefinition(BaseModel):
    """Tool definition for model to call."""

    name: str = Field(..., description="Tool name")
    description: str = Field(..., description="Tool description")
    input_schema: dict[str, Any] = Field(..., description="JSON Schema for tool parameters")
    allowed_callers: list[str] = Field(
        default=["direct"],
        description="Who can call this tool: direct, code_execution_20250825",
    )


class CompletionRequest(BaseModel):
    """Request body for completion endpoint."""

    model: str = Field(..., description="Model identifier (e.g., claude-sonnet-4-5-20250514)")
    messages: list[MessageInput] = Field(..., description="Conversation messages")
    max_tokens: int = Field(default=4096, ge=1, le=100000, description="Max tokens in response")
    temperature: float = Field(default=1.0, ge=0.0, le=2.0, description="Sampling temperature")
    session_id: str | None = Field(default=None, description="Existing session ID to continue")
    project_id: str = Field(default="default", description="Project ID for session tracking")
    enable_caching: bool = Field(default=True, description="Enable prompt caching (Claude only)")
    cache_ttl: str = Field(default="ephemeral", description="Cache TTL: ephemeral (5min) or 1h")
    persist_session: bool = Field(default=True, description="Persist messages to database")
    # Extended Thinking support (Claude only)
    budget_tokens: int | None = Field(
        default=None,
        ge=1024,
        le=128000,
        description="Token budget for extended thinking (enables thinking block)",
    )
    auto_thinking: bool = Field(
        default=False,
        description="Auto-enable thinking for complex requests",
    )
    # Tool calling support
    tools: list[ToolDefinition] | None = Field(
        default=None,
        description="Tool definitions for model to call",
    )
    enable_programmatic_tools: bool = Field(
        default=False,
        description="Enable code execution to call tools programmatically (Claude only)",
    )
    container_id: str | None = Field(
        default=None,
        description="Container ID for code execution continuity (Claude only)",
    )


class CacheInfo(BaseModel):
    """Cache usage information."""

    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_hit_rate: float = 0.0


class UsageInfo(BaseModel):
    """Token usage information."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    cache: CacheInfo | None = None


class ContextUsageInfo(BaseModel):
    """Context window usage information."""

    used_tokens: int = Field(..., description="Tokens currently in context")
    limit_tokens: int = Field(..., description="Model's context window limit")
    percent_used: float = Field(..., description="Percentage of context used")
    remaining_tokens: int = Field(..., description="Tokens available")
    warning: str | None = Field(default=None, description="Warning if approaching limit")


class ThinkingInfo(BaseModel):
    """Extended thinking information."""

    content: str = Field(..., description="Thinking content from the model")
    tokens: int | None = Field(default=None, description="Tokens used for thinking")
    budget_used: int | None = Field(default=None, description="Budget tokens actually used")
    cost_usd: float | None = Field(default=None, description="Estimated cost of thinking in USD")


class ToolCallInfo(BaseModel):
    """Information about a tool call from the model."""

    id: str = Field(..., description="Unique ID for this tool call")
    name: str = Field(..., description="Tool name")
    input: dict[str, Any] = Field(..., description="Tool input parameters")
    caller_type: str = Field(
        default="direct", description="Who initiated: direct or code_execution"
    )
    caller_tool_id: str | None = Field(
        default=None, description="Tool ID if called from code execution"
    )


class ContainerInfo(BaseModel):
    """Container state for programmatic tool calling."""

    id: str = Field(..., description="Container ID for continuity")
    expires_at: str = Field(..., description="Container expiration timestamp")


class CompletionResponse(BaseModel):
    """Response body for completion endpoint."""

    content: str = Field(..., description="Generated content")
    model: str = Field(..., description="Model used for generation")
    provider: str = Field(..., description="Provider that served the request")
    usage: UsageInfo = Field(..., description="Token usage")
    context_usage: ContextUsageInfo | None = Field(default=None, description="Context window usage")
    session_id: str = Field(..., description="Session ID for continuing conversation")
    finish_reason: str | None = Field(default=None, description="Why generation stopped")
    from_cache: bool = Field(default=False, description="Whether response was served from cache")
    # Extended thinking (Claude only)
    thinking: ThinkingInfo | None = Field(default=None, description="Extended thinking content")
    # Tool calling (when model requests tool execution)
    tool_calls: list[ToolCallInfo] | None = Field(
        default=None,
        description="Tool calls requested by model (caller must execute and continue)",
    )
    container: ContainerInfo | None = Field(
        default=None,
        description="Container state for code execution continuity",
    )


def _get_provider(model: str) -> str:
    """Determine provider from model name."""
    model_lower = model.lower()
    if "claude" in model_lower:
        return "claude"
    elif "gemini" in model_lower:
        return "gemini"
    else:
        # Default to claude for unknown models
        return "claude"


# Auto-thinking detection configuration
# Inspired by Claude Code UX: Tab toggle, "ultrathink" trigger, sticky state
# See: https://claudelog.com/faqs/how-to-toggle-thinking-in-claude-code/

# Keywords that suggest complex reasoning where thinking helps
_THINKING_TRIGGERS = [
    # Explicit thinking requests (Claude Code style)
    "ultrathink",  # Maximum budget trigger
    "think hard",
    "think carefully",
    "think step by step",
    # Analysis tasks
    "analyze",
    "evaluate",
    "compare",
    "explain why",
    # Reasoning tasks
    "reason",
    "think through",
    "consider carefully",
    # Code tasks
    "debug",
    "review code",
    "find the bug",
    "what's wrong",
    "refactor",
    # Complexity markers
    "multi-step",
    "complex",
    "edge cases",
]

# Budget presets for different thinking depths
_THINKING_BUDGETS = {
    "ultrathink": 64000,  # Maximum extended thinking
    "think hard": 32000,  # Deep reasoning
    "think carefully": 16000,  # Standard extended thinking
    "default": 16000,  # Auto-thinking default
}


def _get_thinking_budget_from_triggers(content: str) -> int | None:
    """Detect explicit thinking trigger and return appropriate budget.

    Returns:
        Token budget if explicit trigger found, None otherwise.
    """
    content_lower = content.lower()
    for trigger, budget in _THINKING_BUDGETS.items():
        if trigger != "default" and trigger in content_lower:
            return budget
    return None


def _extract_text_content(content: str | list[dict[str, Any]]) -> str:
    """Extract text content from message content.

    Args:
        content: String or list of content blocks.

    Returns:
        Extracted text content.
    """
    if isinstance(content, str):
        return content
    # Extract text from content blocks
    texts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            texts.append(block.get("text", ""))
        elif isinstance(block, str):
            texts.append(block)
    return " ".join(texts)


def _should_enable_thinking(messages: list[Message]) -> bool:
    """Detect if request would benefit from extended thinking.

    Triggers on:
    - Explicit thinking keywords (ultrathink, think hard, etc.)
    - Keywords suggesting complex reasoning
    - Multi-step instructions (numbered lists)
    - Code review/analysis requests
    """
    # Check the last user message
    for msg in reversed(messages):
        if msg.role == "user":
            text_content = _extract_text_content(msg.content)
            content_lower = text_content.lower()
            for trigger in _THINKING_TRIGGERS:
                if trigger in content_lower:
                    return True
            # Also trigger on numbered steps (1. 2. 3.)
            if any(f"{i}." in text_content for i in range(1, 10)):
                return True
            break
    return False


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


def clear_adapter_cache() -> None:
    """Clear the adapter cache. Useful for testing."""
    _adapter_cache.clear()


async def _get_or_create_session(
    db: AsyncSession,
    session_id: str | None,
    project_id: str,
    provider: str,
    model: str,
) -> tuple[DBSession, list[Message]]:
    """Get existing session or create new one. Returns session and loaded messages."""
    if session_id:
        # Try to load existing session
        result = await db.execute(
            select(DBSession)
            .options(selectinload(DBSession.messages))
            .where(DBSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if session:
            # Load existing messages as context
            context_messages = [
                Message(role=m.role, content=m.content)  # type: ignore[arg-type]
                for m in sorted(session.messages, key=lambda x: x.created_at)
            ]
            return session, context_messages

    # Create new session
    new_session_id = session_id or str(uuid.uuid4())
    session = DBSession(
        id=new_session_id,
        project_id=project_id,
        provider=provider,
        model=model,
        status="active",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session, []


async def _save_messages(
    db: AsyncSession,
    session_id: str,
    user_messages: list[MessageInput],
    assistant_content: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Save user messages and assistant response to database."""
    # Save user messages (only new ones - last message typically)
    for msg in user_messages:
        if msg.role in ("user", "system"):
            db_msg = DBMessage(
                session_id=session_id,
                role=msg.role,
                content=msg.content,
            )
            db.add(db_msg)

    # Save assistant response
    db_msg = DBMessage(
        session_id=session_id,
        role="assistant",
        content=assistant_content,
        tokens=output_tokens,
    )
    db.add(db_msg)
    await db.commit()


async def _update_provider_metadata(
    db: AsyncSession,
    session: DBSession,
    cache_metrics: dict[str, Any] | None,
) -> None:
    """Update session with provider-specific metadata like cache info."""
    if not cache_metrics:
        return

    # Merge with existing metadata
    existing = session.provider_metadata or {}
    existing["cache"] = {
        "last_cache_creation_tokens": cache_metrics.get("cache_creation_input_tokens", 0),
        "last_cache_read_tokens": cache_metrics.get("cache_read_input_tokens", 0),
        "total_cache_creation_tokens": existing.get("cache", {}).get(
            "total_cache_creation_tokens", 0
        )
        + cache_metrics.get("cache_creation_input_tokens", 0),
        "total_cache_read_tokens": existing.get("cache", {}).get("total_cache_read_tokens", 0)
        + cache_metrics.get("cache_read_input_tokens", 0),
    }
    session.provider_metadata = existing
    await db.commit()


@router.post("/complete", response_model=CompletionResponse)
async def complete(
    request: CompletionRequest,
    x_skip_cache: Annotated[str | None, Header(alias="X-Skip-Cache")] = None,
    db: Annotated[AsyncSession | None, Depends(get_db)] = None,
) -> CompletionResponse:
    """
    Generate a completion for the given messages.

    Routes to appropriate provider (Claude or Gemini) based on model name.
    Optionally persists messages to database for session continuity.

    Headers:
        X-Skip-Cache: Set to "true" to bypass response cache
    """
    # Determine provider
    provider = _get_provider(request.model)
    skip_cache = x_skip_cache and x_skip_cache.lower() == "true"

    # Get or create session if persistence is enabled
    session: DBSession | None = None
    context_messages: list[Message] = []
    session_id = request.session_id or str(uuid.uuid4())

    if request.persist_session and db:
        session, context_messages = await _get_or_create_session(
            db, request.session_id, request.project_id, provider, request.model
        )
        session_id = session.id

    # Build full message list: context + new messages
    # Only add new messages that aren't already in context
    new_messages = [
        Message(role=m.role, content=m.content)  # type: ignore[arg-type]
        for m in request.messages
    ]

    # If we have context, only send the last user message as new
    # The context already contains prior conversation
    if context_messages:
        all_messages = context_messages + new_messages
    else:
        all_messages = new_messages

    messages_dict = [{"role": m.role, "content": m.content} for m in all_messages]

    # Check context window usage before proceeding
    # NOTE: We intentionally do NOT auto-compress here. Per Anthropic's harness
    # architecture, the caller (SummitFlow) should handle context management by:
    # 1. Monitoring context_usage in responses
    # 2. Checkpointing work (git commit, task update) when approaching limits
    # 3. Starting a fresh session with targeted file reads
    # This preserves the external scaffolding pattern that enables long-running agents.
    estimated_input_tokens = count_message_tokens(messages_dict)
    context_usage_info: ContextUsageInfo | None = None
    if db and session:
        can_proceed, ctx_usage = await check_context_before_request(
            db, session_id, request.model, estimated_input_tokens
        )
        if not can_proceed:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Context window limit exceeded ({ctx_usage.percent_used:.0%} used). "
                    "Start a new session or reduce conversation history."
                ),
            )
        context_usage_info = ContextUsageInfo(
            used_tokens=ctx_usage.used_tokens,
            limit_tokens=ctx_usage.limit_tokens,
            percent_used=ctx_usage.percent_used,
            remaining_tokens=ctx_usage.remaining_tokens,
            warning=ctx_usage.warning,
        )
        if should_emit_warning(ctx_usage.percent_used):
            logger.warning(f"Session {session_id}: {ctx_usage.warning}")

    # Check response cache first (unless bypassed)
    cache = get_response_cache()
    if not skip_cache:
        cached = await cache.get(
            model=request.model,
            messages=messages_dict,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
        )
        if cached:
            logger.info(f"Returning cached response for {request.model}")
            # Still save to session if persisting
            if request.persist_session and db and session:
                await _save_messages(
                    db,
                    session_id,
                    request.messages,
                    cached.content,
                    cached.input_tokens,
                    cached.output_tokens,
                )
            # Log token usage for cached response too
            if request.persist_session and db and session:
                cost = estimate_cost(cached.input_tokens, cached.output_tokens, request.model)
                await log_token_usage(
                    db,
                    session_id,
                    request.model,
                    cached.input_tokens,
                    cached.output_tokens,
                    cost.total_cost_usd,
                )
                await db.commit()
            return CompletionResponse(
                content=cached.content,
                model=cached.model,
                provider=cached.provider,
                usage=UsageInfo(
                    input_tokens=cached.input_tokens,
                    output_tokens=cached.output_tokens,
                    total_tokens=cached.input_tokens + cached.output_tokens,
                    cache=None,
                ),
                context_usage=context_usage_info,
                session_id=session_id,
                finish_reason=cached.finish_reason,
                from_cache=True,
            )

    try:
        # Get adapter
        adapter = _get_adapter(provider)

        # Determine thinking budget
        thinking_budget = request.budget_tokens
        if not thinking_budget:
            # Check for explicit thinking triggers (ultrathink, think hard, etc.)
            last_user_content = next(
                (m.content for m in reversed(all_messages) if m.role == "user"), ""
            )
            last_user_msg = _extract_text_content(last_user_content)
            thinking_budget = _get_thinking_budget_from_triggers(last_user_msg)

        if request.auto_thinking and not thinking_budget:
            # Auto-detect complex requests and enable thinking
            if _should_enable_thinking(all_messages):
                thinking_budget = _THINKING_BUDGETS["default"]

        # Convert tools to API format if provided
        tools_api: list[dict[str, Any]] | None = None
        if request.tools:
            tools_api = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                    **(
                        {"allowed_callers": t.allowed_callers}
                        if t.allowed_callers != ["direct"]
                        else {}
                    ),
                }
                for t in request.tools
            ]

        # Make completion request with full context
        result: CompletionResult = await adapter.complete(
            messages=all_messages,
            model=request.model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            enable_caching=request.enable_caching,
            cache_ttl=request.cache_ttl,
            budget_tokens=thinking_budget,
            tools=tools_api,
            enable_programmatic_tools=request.enable_programmatic_tools,
            container_id=request.container_id,
        )

        # Cache the response for future identical requests
        if not skip_cache:
            await cache.set(
                model=request.model,
                messages=messages_dict,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                content=result.content,
                provider=result.provider,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                finish_reason=result.finish_reason,
            )

        # Save messages to database if persistence enabled
        if request.persist_session and db and session:
            await _save_messages(
                db,
                session_id,
                request.messages,
                result.content,
                result.input_tokens,
                result.output_tokens,
            )
            # Log token usage for cost tracking
            cost = estimate_cost(result.input_tokens, result.output_tokens, request.model)
            await log_token_usage(
                db,
                session_id,
                request.model,
                result.input_tokens,
                result.output_tokens,
                cost.total_cost_usd,
            )
            # Update provider metadata (cache info, etc.)
            if result.cache_metrics:
                await _update_provider_metadata(
                    db,
                    session,
                    {
                        "cache_creation_input_tokens": result.cache_metrics.cache_creation_input_tokens,
                        "cache_read_input_tokens": result.cache_metrics.cache_read_input_tokens,
                    },
                )
            await db.commit()

        # Build cache info if available
        cache_info = None
        if result.cache_metrics:
            cache_info = CacheInfo(
                cache_creation_input_tokens=result.cache_metrics.cache_creation_input_tokens,
                cache_read_input_tokens=result.cache_metrics.cache_read_input_tokens,
                cache_hit_rate=result.cache_metrics.cache_hit_rate,
            )

        # Build thinking info if available
        thinking_info = None
        if result.thinking_content:
            # Estimate thinking cost (thinking tokens count as input tokens)
            thinking_cost = None
            if result.thinking_tokens:
                cost_estimate = estimate_cost(result.thinking_tokens, 0, request.model)
                thinking_cost = cost_estimate.input_cost_usd

            thinking_info = ThinkingInfo(
                content=result.thinking_content,
                tokens=result.thinking_tokens,
                budget_used=thinking_budget,
                cost_usd=thinking_cost,
            )

        # Build tool calls info if available
        tool_calls_info: list[ToolCallInfo] | None = None
        if result.tool_calls:
            tool_calls_info = [
                ToolCallInfo(
                    id=tc.id,
                    name=tc.name,
                    input=tc.input,
                    caller_type=tc.caller_type,
                    caller_tool_id=tc.caller_tool_id,
                )
                for tc in result.tool_calls
            ]

        # Build container info if available
        container_info: ContainerInfo | None = None
        if result.container:
            container_info = ContainerInfo(
                id=result.container.id,
                expires_at=result.container.expires_at,
            )

        return CompletionResponse(
            content=result.content,
            model=result.model,
            provider=result.provider,
            usage=UsageInfo(
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                total_tokens=result.input_tokens + result.output_tokens,
                cache=cache_info,
            ),
            context_usage=context_usage_info,
            session_id=session_id,
            finish_reason=result.finish_reason,
            from_cache=False,
            thinking=thinking_info,
            tool_calls=tool_calls_info,
            container=container_info,
        )

    except ValueError as e:
        # API key not configured
        logger.error(f"Configuration error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Configuration error: {e}. Check environment variables (ANTHROPIC_API_KEY, GEMINI_API_KEY).",
        ) from e

    except RateLimitError as e:
        logger.warning(f"Rate limit for {e.provider}")
        retry_after = str(int(e.retry_after)) if e.retry_after else "60"
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit exceeded for {e.provider}. "
                f"Wait {retry_after}s before retrying. Consider using prompt caching (enable_caching: true)."
            ),
            headers={"Retry-After": retry_after},
        ) from e

    except AuthenticationError as e:
        logger.error(f"Auth error for {e.provider}")
        env_var = "ANTHROPIC_API_KEY" if e.provider == "claude" else "GEMINI_API_KEY"
        raise HTTPException(
            status_code=401,
            detail=f"Authentication failed for {e.provider}. Verify {env_var} is set and valid.",
        ) from e

    except ProviderError as e:
        logger.error(f"Provider error: {e}")
        status_code = e.status_code or 500
        detail = str(e)
        if e.retriable:
            detail += " This error may be transient; retry may succeed."
        raise HTTPException(status_code=status_code, detail=detail) from e

    except Exception as e:
        logger.exception(f"Unexpected error in /complete: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error. Check logs for details.",
        ) from e


# Estimation schemas and endpoint
class EstimateRequest(BaseModel):
    """Request body for cost estimation endpoint."""

    model: str = Field(..., description="Model identifier")
    messages: list[MessageInput] = Field(..., description="Conversation messages")
    max_tokens: int = Field(default=4096, ge=1, le=100000, description="Max tokens in response")


class EstimateResponse(BaseModel):
    """Response body for cost estimation endpoint."""

    input_tokens: int = Field(..., description="Estimated input tokens")
    estimated_output_tokens: int = Field(..., description="Estimated output tokens")
    total_tokens: int = Field(..., description="Total estimated tokens")
    estimated_cost_usd: float = Field(..., description="Estimated cost in USD")
    context_limit: int = Field(..., description="Model context limit")
    context_usage_percent: float = Field(..., description="Percentage of context used")
    context_warning: str | None = Field(default=None, description="Warning if approaching limit")


@router.post("/estimate", response_model=EstimateResponse)
async def estimate(request: EstimateRequest) -> EstimateResponse:
    """
    Estimate tokens and cost before making a completion request.

    Returns token counts, estimated cost, and context limit warnings.
    """
    messages_dict = [{"role": m.role, "content": m.content} for m in request.messages]

    estimate_result = estimate_request(
        messages=messages_dict,
        model=request.model,
        max_tokens=request.max_tokens,
    )

    return EstimateResponse(
        input_tokens=estimate_result.input_tokens,
        estimated_output_tokens=estimate_result.estimated_output_tokens,
        total_tokens=estimate_result.total_tokens,
        estimated_cost_usd=estimate_result.estimated_cost_usd,
        context_limit=estimate_result.context_limit,
        context_usage_percent=estimate_result.context_usage_percent,
        context_warning=estimate_result.context_warning,
    )
