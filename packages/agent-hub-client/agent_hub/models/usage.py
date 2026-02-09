"""Usage and metrics models for Agent Hub client."""

from pydantic import BaseModel, Field


class CacheInfo(BaseModel):
    """Prompt cache usage information."""

    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_hit_rate: float = 0.0


class UsageInfo(BaseModel):
    """Token usage information."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    cache: CacheInfo | None = None


class ContextUsage(BaseModel):
    """Context window usage information."""

    used_tokens: int = Field(..., description="Tokens currently in context")
    limit_tokens: int = Field(..., description="Model's context window limit")
    percent_used: float = Field(..., description="Percentage of context used")
    remaining_tokens: int = Field(..., description="Tokens available")
    warning: str | None = Field(
        default=None, description="Warning if approaching limit"
    )
