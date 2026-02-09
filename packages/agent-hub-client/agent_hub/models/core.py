"""Core completion and routing models for Agent Hub client."""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from agent_hub.models.agent import AgentProgress
from agent_hub.models.content import MessageInput
from agent_hub.models.tools import ToolCall, ToolDefinition
from agent_hub.models.usage import ContextUsage, UsageInfo


class ContainerInfo(BaseModel):
    """Container state for programmatic tool calling."""

    id: str = Field(..., description="Container ID for continuity")
    expires_at: str = Field(..., description="Container expiration timestamp")


class RoutingConfig(BaseModel):
    """Configuration for capability-based model routing.

    Instead of specifying a model directly, consumers can request a capability
    and let the routing layer select the appropriate model.
    """

    capability: str | None = Field(
        default=None,
        description=(
            "Model capability: coding, planning, review, fast_task, "
            "worker, supervisor_primary, supervisor_audit. "
            "If provided, overrides the model field."
        ),
    )
    provider_preference: str | None = Field(
        default=None,
        description="Prefer a specific provider: 'claude' or 'gemini'. Optional.",
    )
    is_autonomous: bool = Field(
        default=False,
        description=(
            "If True, safety directive is injected into system prompt. "
            "Required for autonomous/self-healing agents."
        ),
    )


class CompletionRequest(BaseModel):
    """Request body for completion endpoint."""

    model: str = Field(..., description="Model identifier")
    messages: list[MessageInput] = Field(..., description="Conversation messages")
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)
    session_id: str | None = Field(default=None)
    project_id: str = Field(default="default")
    enable_caching: bool = Field(default=True)
    cache_ttl: str = Field(default="ephemeral")
    persist_session: bool = Field(default=True)
    # Capability-based routing
    routing_config: RoutingConfig | None = Field(
        default=None,
        description=(
            "Capability-based model routing. If routing_config.capability is set, "
            "it overrides the model field to select an appropriate model."
        ),
    )
    # Tool calling support
    tools: list[ToolDefinition] | None = Field(
        default=None, description="Tool definitions"
    )
    enable_programmatic_tools: bool = Field(
        default=False, description="Enable code execution"
    )
    container_id: str | None = Field(
        default=None, description="Container ID for continuity"
    )


class CompletionResponse(BaseModel):
    """Response from completion endpoint."""

    content: str = Field(..., description="Generated content")
    model: str = Field(..., description="Model used")
    provider: str = Field(..., description="Provider that served request")
    usage: UsageInfo = Field(..., description="Token usage")
    context_usage: ContextUsage | None = Field(default=None)
    session_id: str = Field(..., description="Session ID")
    finish_reason: str | None = Field(default=None)
    from_cache: bool = Field(default=False)
    # Tool calling (when model requests tool execution)
    tool_calls: list[ToolCall] | None = Field(
        default=None, description="Tool calls to execute"
    )
    container: ContainerInfo | None = Field(default=None, description="Container state")
    # Agentic execution fields (populated when max_turns > 1 or execute_tools=True)
    turns: int = Field(default=1, description="Number of agentic turns executed")
    tool_calls_count: int = Field(
        default=0, description="Total number of tool calls made"
    )
    progress_log: list[AgentProgress] | None = Field(
        default=None, description="Progress log from agentic execution"
    )
    trace_id: str | None = Field(
        default=None, description="Trace ID for event correlation"
    )
    cited_uuids: list[str] = Field(
        default_factory=list, description="UUIDs of memory items referenced/cited"
    )
    memory_uuids: list[str] = Field(
        default_factory=list,
        description="Memory episode UUIDs loaded for this execution",
    )

    @field_validator("memory_uuids", "cited_uuids", mode="before")
    @classmethod
    def _coerce_to_list(cls, v: Any) -> list[str]:
        """Convert None or comma-separated string to list for memory/citation fields."""
        if v is None:
            return []
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v


class StreamChunk(BaseModel):
    """Chunk from streaming response."""

    type: Literal["content", "tool_use", "done", "cancelled", "error"] = Field(
        ..., description="Event type"
    )
    content: str = Field(default="", description="Content for 'content' events")
    input_tokens: int | None = Field(default=None)
    output_tokens: int | None = Field(default=None)
    finish_reason: str | None = Field(default=None)
    error: str | None = Field(default=None)
    # Tool use streaming (when type="tool_use")
    tool_call: ToolCall | None = Field(
        default=None, description="Tool call for 'tool_use' events"
    )
