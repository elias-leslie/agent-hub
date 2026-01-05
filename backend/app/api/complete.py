"""Completion API endpoint."""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.adapters.base import (
    AuthenticationError,
    CompletionResult,
    Message,
    ProviderError,
    RateLimitError,
)
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter

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


class UsageInfo(BaseModel):
    """Token usage information."""

    input_tokens: int
    output_tokens: int
    total_tokens: int


class CompletionResponse(BaseModel):
    """Response body for completion endpoint."""

    content: str = Field(..., description="Generated content")
    model: str = Field(..., description="Model used for generation")
    provider: str = Field(..., description="Provider that served the request")
    usage: UsageInfo = Field(..., description="Token usage")
    session_id: str = Field(..., description="Session ID for continuing conversation")
    finish_reason: str | None = Field(default=None, description="Why generation stopped")


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


def _get_adapter(provider: str) -> ClaudeAdapter | GeminiAdapter:
    """Get adapter instance for provider."""
    if provider == "claude":
        return ClaudeAdapter()
    elif provider == "gemini":
        return GeminiAdapter()
    else:
        raise ValueError(f"Unknown provider: {provider}")


@router.post("/complete", response_model=CompletionResponse)
async def complete(request: CompletionRequest) -> CompletionResponse:
    """
    Generate a completion for the given messages.

    Routes to appropriate provider (Claude or Gemini) based on model name.
    """
    # Determine provider
    provider = _get_provider(request.model)

    try:
        # Get adapter
        adapter = _get_adapter(provider)

        # Convert messages
        messages = [Message(role=m.role, content=m.content) for m in request.messages]  # type: ignore[arg-type]

        # Make completion request
        result: CompletionResult = await adapter.complete(
            messages=messages,
            model=request.model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
        )

        # Generate session ID if not provided
        session_id = request.session_id or str(uuid.uuid4())

        return CompletionResponse(
            content=result.content,
            model=result.model,
            provider=result.provider,
            usage=UsageInfo(
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                total_tokens=result.input_tokens + result.output_tokens,
            ),
            session_id=session_id,
            finish_reason=result.finish_reason,
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
