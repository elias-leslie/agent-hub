"""Response schemas for completion API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.api.orchestration_models import AgentProgressInfo

from .usage_schemas import (
    ContainerInfo,
    ContextUsageInfo,
    OutputUsageInfo,
    ThinkingInfo,
    ToolCallInfo,
    UsageInfo,
)


class CompletionResponse(BaseModel):
    """Response body for completion endpoint."""

    content: str = Field(..., description="Generated content")
    model: str = Field(..., description="Model used for generation")
    provider: str = Field(..., description="Provider that served the request")
    usage: UsageInfo = Field(..., description="Token usage")
    context_usage: ContextUsageInfo | None = Field(default=None, description="Context window usage")
    output_usage: OutputUsageInfo | None = Field(
        default=None, description="Output token usage and truncation info"
    )
    session_id: str = Field(..., description="Session ID for continuing conversation")
    finish_reason: str | None = Field(default=None, description="Why generation stopped")
    from_cache: bool = Field(default=False, description="Whether response was served from cache")
    thinking: ThinkingInfo | None = Field(default=None, description="Extended thinking content")
    tool_calls: list[ToolCallInfo] | None = Field(
        default=None,
        description="Tool calls requested by model (caller must execute and continue)",
    )
    container: ContainerInfo | None = Field(
        default=None,
        description="Container state for code execution continuity",
    )
    memory_facts_injected: int = Field(
        default=0,
        description="Number of memory facts injected into context",
    )
    memory_uuids: str | None = Field(
        default=None,
        description="Comma-separated UUIDs of injected memory items (for feedback attribution)",
    )
    agent_used: str | None = Field(
        default=None,
        description="Agent slug that was used (if agent_slug was provided)",
    )
    model_used: str | None = Field(
        default=None,
        description="Actual model used for completion (may differ from requested if fallback)",
    )
    fallback_used: bool = Field(
        default=False,
        description="Whether a fallback model was used due to primary model failure",
    )
    fallback_reason: str | None = Field(
        default=None,
        description="Why the primary model was abandoned, if known",
    )
    turns: int = Field(
        default=1,
        description="Number of agentic turns executed (1 for single completion)",
    )
    tool_calls_count: int = Field(
        default=0,
        description="Total number of tool calls made during execution",
    )
    progress_log: list[AgentProgressInfo] | None = Field(
        default=None,
        description="Progress log from agentic execution (only when max_turns > 1 or execute_tools=True)",
    )
    trace_id: str | None = Field(
        default=None,
        description="Trace ID for event correlation",
    )
    cited_uuids: list[str] = Field(
        default_factory=list,
        description="UUIDs of memory items referenced/cited in response",
    )
    routing_mode: str | None = Field(default=None, description="Agent Hub routing mode used")
    workload_profile: str | None = Field(default=None, description="Resolved workload profile")
    routing_decision_id: str | None = Field(default=None, description="Routing decision audit id")
    auto_candidate_model_id: str | None = Field(default=None, description="Auto-route candidate model id")
    routing_canary_percent: float | None = Field(default=None, description="Auto-canary percent applied")


class AsyncTaskResponse(BaseModel):
    """Response for async completion dispatch (202 Accepted)."""

    task_id: str = Field(..., description="Task ID for polling")
    session_id: str = Field(..., description="Session ID for event correlation")
    status: str = Field(default="pending", description="Initial task status")
    poll_url: str = Field(..., description="URL to poll for task status")
    events_channel: str = Field(..., description="Stream channel for real-time events")
    trace_id: str | None = Field(default=None, description="Trace ID for event correlation")


class AsyncTaskStatusResponse(BaseModel):
    """Response for async task status polling."""

    task_id: str = Field(..., description="Task ID")
    session_id: str | None = Field(default=None, description="Session ID")
    status: str = Field(..., description="Task status: pending, started, completed, failed, cancelled, unknown")
    result: CompletionResponse | None = Field(default=None, description="Completion result when done")
    error: str | None = Field(default=None, description="Error message if failed")
    progress: dict[str, Any] | None = Field(default=None, description="Latest progress data")


class StreamingChunk(BaseModel):
    """Chunk in SSE streaming response."""

    type: str = Field(..., description="Event type: content, tool_use, done, or error")
    seq: int | None = Field(default=None, description="Monotonic sequence number for ordering and dedup")
    content: str | None = Field(default=None, description="Content chunk for 'content' events")
    model: str | None = Field(default=None, description="Model used")
    provider: str | None = Field(default=None, description="Provider name")
    input_tokens: int | None = Field(default=None, description="Input tokens used")
    output_tokens: int | None = Field(default=None, description="Output tokens generated")
    finish_reason: str | None = Field(default=None, description="Why generation stopped")
    session_id: str | None = Field(default=None, description="Session ID")
    agent_used: str | None = Field(default=None, description="Agent slug if used")
    model_used: str | None = Field(default=None, description="Actual model used")
    model_display_name: str | None = Field(default=None, description="Human-readable model name from catalog")
    fallback_used: bool | None = Field(default=None, description="Whether fallback was used")
    routing_mode: str | None = Field(default=None, description="Agent Hub routing mode used")
    workload_profile: str | None = Field(default=None, description="Resolved workload profile")
    routing_decision_id: str | None = Field(default=None, description="Routing decision audit id")
    auto_candidate_model_id: str | None = Field(default=None, description="Auto-route candidate model id")
    routing_canary_percent: float | None = Field(default=None, description="Auto-canary percent applied")
    error: str | None = Field(default=None, description="Error message for 'error' events")
    # Cost and cache fields (populated on 'done' events)
    cost_usd: float | None = Field(default=None, description="Estimated cost in USD")
    thinking_tokens: int | None = Field(default=None, description="Tokens used for thinking")
    cache_read_tokens: int | None = Field(default=None, description="Cached input tokens read")
    cache_write_tokens: int | None = Field(default=None, description="Cached input tokens written")
    # Tool use fields (for streaming tool calls to frontend)
    tool_id: str | None = Field(default=None, description="Tool call ID")
    tool_name: str | None = Field(default=None, description="Tool name called")
    tool_input: dict[str, Any] | None = Field(default=None, description="Tool call input")
    # Tool result fields (for streaming tool execution results to frontend)
    tool_result: str | None = Field(default=None, description="Tool execution result content")
    tool_status: str | None = Field(default=None, description="Tool status: running, complete, or error")


class EstimateResponse(BaseModel):
    """Response body for cost estimation endpoint."""

    input_tokens: int = Field(..., description="Estimated input tokens")
    estimated_output_tokens: int = Field(..., description="Estimated output tokens")
    total_tokens: int = Field(..., description="Total estimated tokens")
    estimated_cost_usd: float = Field(..., description="Estimated cost in USD")
    context_limit: int = Field(..., description="Model context limit")
    context_usage_percent: float = Field(..., description="Percentage of context used")
    context_warning: str | None = Field(default=None, description="Warning if approaching limit")
