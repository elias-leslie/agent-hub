"""Usage and info schemas for completion API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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


class OutputUsageInfo(BaseModel):
    """Output token usage and truncation information."""

    output_tokens: int = Field(..., description="Actual tokens generated")
    max_tokens_requested: int = Field(..., description="max_tokens value used for request")
    model_limit: int = Field(..., description="Model's max output capability")
    was_truncated: bool = Field(
        ..., description="True if response was truncated (finish_reason=max_tokens)"
    )
    warning: str | None = Field(default=None, description="Truncation or validation warning")


class ThinkingInfo(BaseModel):
    """Extended thinking information."""

    content: str = Field(..., description="Thinking content from the model")
    tokens: int | None = Field(default=None, description="Tokens used for thinking")
    level_used: str | None = Field(default=None, description="Thinking level used")
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
