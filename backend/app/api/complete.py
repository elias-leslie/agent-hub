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
from app.models import Message as DBMessage, Session as DBSession
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
    """Input message in conversation."""

    role: str = Field(..., description="Message role: user, assistant, or system")
    content: str = Field(..., description="Message content")


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
        "total_cache_creation_tokens": existing.get("cache", {}).get("total_cache_creation_tokens", 0)
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
                detail=ctx_usage.warning or "Context window limit exceeded",
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
                    db, session_id, request.messages, cached.content,
                    cached.input_tokens, cached.output_tokens
                )
            # Log token usage for cached response too
            if request.persist_session and db and session:
                cost = estimate_cost(cached.input_tokens, cached.output_tokens, request.model)
                await log_token_usage(
                    db, session_id, request.model,
                    cached.input_tokens, cached.output_tokens, cost.total_cost_usd
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

        # Make completion request with full context
        result: CompletionResult = await adapter.complete(
            messages=all_messages,
            model=request.model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            enable_caching=request.enable_caching,
            cache_ttl=request.cache_ttl,
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
                db, session_id, request.messages, result.content,
                result.input_tokens, result.output_tokens
            )
            # Log token usage for cost tracking
            cost = estimate_cost(result.input_tokens, result.output_tokens, request.model)
            await log_token_usage(
                db, session_id, request.model,
                result.input_tokens, result.output_tokens, cost.total_cost_usd
            )
            # Update provider metadata (cache info, etc.)
            if result.cache_metrics:
                await _update_provider_metadata(
                    db, session,
                    {
                        "cache_creation_input_tokens": result.cache_metrics.cache_creation_input_tokens,
                        "cache_read_input_tokens": result.cache_metrics.cache_read_input_tokens,
                    }
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
        )

    except ValueError as e:
        # API key not configured
        logger.error(f"Configuration error: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e

    except RateLimitError as e:
        logger.warning(f"Rate limit for {e.provider}")
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded for {e.provider}",
            headers={"Retry-After": str(int(e.retry_after)) if e.retry_after else "60"},
        ) from e

    except AuthenticationError as e:
        logger.error(f"Auth error for {e.provider}")
        raise HTTPException(status_code=401, detail=f"Authentication failed for {e.provider}") from e

    except ProviderError as e:
        logger.error(f"Provider error: {e}")
        status_code = e.status_code or 500
        raise HTTPException(status_code=status_code, detail=str(e)) from e

    except Exception as e:
        logger.exception(f"Unexpected error in /complete: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


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
