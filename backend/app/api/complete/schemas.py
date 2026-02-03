"""Request/Response schemas for completion API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.api.orchestration_models import AgentProgressInfo


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


class ResponseFormat(BaseModel):
    """Response format specification for structured output (JSON mode)."""

    type: str = Field(
        default="text",
        description="Output type: 'text' (default) or 'json_object' for JSON mode",
    )
    schema_: dict[str, Any] | None = Field(
        default=None,
        alias="schema",
        description="JSON Schema for validating structured output (optional)",
    )

    model_config = {"populate_by_name": True}


class PermissionConfigInput(BaseModel):
    """Permission configuration for tool execution (optional override).

    NOTE: Agents have tool_permissions stored in the database which are used
    by default. This API parameter overrides the agent's stored settings.

    Supports three modes:
    - YOLO: Auto-approve all tools without asking (default)
    - GRANULAR: Check per-tool allow/deny lists
    """

    mode: str = Field(
        default="yolo",
        pattern="^(yolo|granular)$",
        description="Permission mode: 'yolo' (auto-approve all) or 'granular' (use allow/deny lists)",
    )
    allow_list: list[str] = Field(
        default_factory=list,
        description="Tools to auto-approve in granular mode (e.g., ['bash', 'read_file'])",
    )
    deny_list: list[str] = Field(
        default_factory=list,
        description="Tools to deny in granular mode",
    )


class CompletionRequest(BaseModel):
    """Request body for completion endpoint."""

    model: str | None = Field(
        default=None,
        description="DEPRECATED: Use agent_slug instead. Direct model specification is no longer supported.",
        deprecated=True,
    )
    messages: list[MessageInput] = Field(..., description="Conversation messages")
    temperature: float = Field(default=1.0, ge=0.0, le=2.0, description="Sampling temperature")
    session_id: str | None = Field(default=None, description="Existing session ID to continue")
    project_id: str = Field(..., description="Project ID for session tracking (required)")
    external_id: str | None = Field(
        default=None,
        description="External ID for cost aggregation (e.g., task-123, user-456)",
    )
    enable_caching: bool = Field(default=True, description="Enable prompt caching (Claude only)")
    cache_ttl: str = Field(default="ephemeral", description="Cache TTL: ephemeral (5min) or 1h")
    # Structured output (JSON mode) support
    response_format: ResponseFormat | None = Field(
        default=None,
        description="Response format: {type: 'json_object', schema: {...}} for JSON mode",
    )
    # Extended Thinking support (provider-agnostic)
    thinking_level: str | None = Field(
        default=None,
        pattern="^(minimal|low|medium|high|ultrathink)$",
        description=(
            "Thinking depth level: minimal (Flash only), low, medium, high, ultrathink. "
            "Provider-agnostic - mapped to provider-specific params internally."
        ),
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
    # Memory injection
    use_memory: bool = Field(
        default=False,
        description="Inject relevant context from knowledge graph memory",
    )
    memory_group_id: str | None = Field(
        default=None,
        description="Memory group ID for isolation (defaults to project_id)",
    )
    # Agent-based routing
    agent_slug: str | None = Field(
        default=None,
        description=(
            "Agent slug for routing (e.g., 'coder', 'planner'). When provided, "
            "loads agent config from database, injects mandates, and uses fallback chains."
        ),
    )
    # SSE Streaming (unified API)
    stream: bool = Field(
        default=False,
        description="Enable SSE streaming. Returns text/event-stream with data: {json} format.",
    )
    # Agentic execution params (enables multi-turn execution with tools)
    max_turns: int = Field(
        default=1,
        ge=1,
        le=50,
        description="Maximum agentic turns. 1 = single completion, >1 = agentic loop with tool execution.",
    )
    working_dir: str | None = Field(
        default=None,
        description="Working directory for tool execution (agentic mode only).",
    )
    execute_tools: bool = Field(
        default=False,
        description="Execute tool calls in an agentic loop. When True, tools are executed and results fed back.",
    )
    permission_config: PermissionConfigInput | None = Field(
        default=None,
        description="Override for agent's tool permissions. If not provided, uses agent's stored tool_permissions.",
    )
    trace_id: str | None = Field(
        default=None,
        description="Trace ID for event correlation (e.g., SummitFlow task_id). "
        "Events are published to Redis for real-time observability.",
    )
    timeout_seconds: float = Field(
        default=300.0,
        ge=1,
        le=3600,
        description="Maximum execution time in seconds (agentic mode only).",
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
    # Memory injection info
    memory_facts_injected: int = Field(
        default=0,
        description="Number of memory facts injected into context",
    )
    # Memory UUIDs for feedback attribution (comma-separated)
    memory_uuids: str | None = Field(
        default=None,
        description="Comma-separated UUIDs of injected memory items (for feedback attribution)",
    )
    # Agent routing transparency
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
    # Agentic execution results
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


class StreamingChunk(BaseModel):
    """Chunk in SSE streaming response."""

    type: str = Field(..., description="Event type: content, done, or error")
    content: str | None = Field(default=None, description="Content chunk for 'content' events")
    # Final event fields (on 'done')
    model: str | None = Field(default=None, description="Model used")
    provider: str | None = Field(default=None, description="Provider name")
    input_tokens: int | None = Field(default=None, description="Input tokens used")
    output_tokens: int | None = Field(default=None, description="Output tokens generated")
    finish_reason: str | None = Field(default=None, description="Why generation stopped")
    session_id: str | None = Field(default=None, description="Session ID")
    # Agent routing info
    agent_used: str | None = Field(default=None, description="Agent slug if used")
    model_used: str | None = Field(default=None, description="Actual model used")
    fallback_used: bool | None = Field(default=None, description="Whether fallback was used")
    # Error fields
    error: str | None = Field(default=None, description="Error message for 'error' events")


class EstimateRequest(BaseModel):
    """Request body for cost estimation endpoint."""

    model: str = Field(..., description="Model identifier")
    messages: list[MessageInput] = Field(..., description="Conversation messages")


class EstimateResponse(BaseModel):
    """Response body for cost estimation endpoint."""

    input_tokens: int = Field(..., description="Estimated input tokens")
    estimated_output_tokens: int = Field(..., description="Estimated output tokens")
    total_tokens: int = Field(..., description="Total estimated tokens")
    estimated_cost_usd: float = Field(..., description="Estimated cost in USD")
    context_limit: int = Field(..., description="Model context limit")
    context_usage_percent: float = Field(..., description="Percentage of context used")
    context_warning: str | None = Field(default=None, description="Warning if approaching limit")
