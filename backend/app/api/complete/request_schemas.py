"""Request schemas for completion API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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
    response_format: ResponseFormat | None = Field(
        default=None,
        description="Response format: {type: 'json_object', schema: {...}} for JSON mode",
    )
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
    use_memory: bool = Field(
        default=True,
        description="Inject relevant context from knowledge graph memory",
    )
    memory_group_id: str | None = Field(
        default=None,
        description="Memory group ID for isolation (defaults to project_id)",
    )
    task_type: str | None = Field(
        default=None,
        description="Task type for triggered reference injection (e.g., 'database', 'frontend', 'backend')",
    )
    phase: str | None = Field(
        default=None,
        description="Subtask phase for phase-triggered reference injection (e.g., 'planning', 'implementation', 'review')",
    )
    agent_slug: str | None = Field(
        default=None,
        description=(
            "Agent slug for routing (e.g., 'coder', 'planner'). When provided, "
            "loads agent config from database, injects mandates, and uses fallback chains."
        ),
    )
    include_roles: list[str] | None = Field(
        default=None,
        description=(
            "Filter which prompt roles to inject. When provided, only agent prompt "
            "assignments with matching roles are included. When None (default), all "
            "assigned prompts are injected. Example: ['system', 'autocode']"
        ),
    )
    stream: bool = Field(
        default=False,
        description="Enable SSE streaming. Returns text/event-stream with data: {json} format.",
    )
    max_turns: int = Field(
        default=1,
        ge=1,
        le=200,
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
    tier_preference: str | None = Field(
        default=None,
        pattern="^(standard|advanced)$",
        description="Model tier preference. 'advanced' uses agent's premium_model_id if configured.",
    )
    current_branch: str | None = Field(
        default=None,
        description="Current git branch for continuity branch scoping (e.g., 'main', 'feature/auth')",
    )
    async_execution: bool = Field(
        default=False,
        description="Run agentic completion asynchronously via background worker. "
        "Returns 202 with task_id for polling. Only applies to agentic requests.",
    )


class EstimateRequest(BaseModel):
    """Request body for cost estimation endpoint."""

    model: str = Field(..., description="Model identifier")
    messages: list[MessageInput] = Field(..., description="Conversation messages")
