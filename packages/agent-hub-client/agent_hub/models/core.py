"""Core completion and routing models for Agent Hub client."""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from agent_hub.models.agent import AgentProgress
from agent_hub.models.tools import ToolCall
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


class NativeContinuation(BaseModel):
    """Delta-context request for a retained Codex native thread."""

    mode: Literal["snapshot", "delta"]
    generation: int
    request_id: str
    expected_turn: int
    context_version: str
    role: Literal["hunter", "reviewer"]
    controller_generation: str
    instruction_hash: str | None = None
    tool_policy_hash: str | None = None
    reasoning_effort: Literal["low", "medium", "high", "xhigh", "max", "ultra"] = "xhigh"
    cyber_access_program: Literal["standard"] | None = None
    close_after: bool = False


class NativeContinuationInfo(BaseModel):
    """Observed receipt for a retained Codex native-thread turn."""

    generation: int
    turn: int
    request_id: str
    context_version: str
    instruction_hash: str
    tool_policy_hash: str
    native_thread_id: str
    native_turn_id: str | None = None
    runtime_status: str
    duplicate: bool = False
    input_mode: str
    reasoning_tokens: int = 0
    usage_known: bool = True


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
    agent_used: str | None = None
    model_used: str | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None
    error_summary: dict[str, Any] | None = None
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
    native_continuation: NativeContinuationInfo | None = None

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

    type: Literal["content", "thinking", "tool_use", "tool_result", "done", "cancelled", "error"] = Field(
        ..., description="Event type"
    )
    content: str = Field(default="", description="Content for 'content' events")
    input_tokens: int | None = Field(default=None)
    output_tokens: int | None = Field(default=None)
    finish_reason: str | None = Field(default=None)
    error: str | None = Field(default=None)
    model: str | None = Field(default=None)
    provider: str | None = Field(default=None)
    session_id: str | None = Field(default=None)
    tool_id: str | None = Field(default=None, description="Tool use/result ID")
    tool_name: str | None = Field(default=None, description="Tool name for streamed tool events")
    tool_input: dict[str, Any] | None = Field(default=None, description="Tool input for 'tool_use' events")
    tool_result: str | None = Field(default=None, description="Tool result content for 'tool_result' events")
    tool_status: str | None = Field(default=None, description="Tool result status for 'tool_result' events")
    tool_call: ToolCall | None = Field(
        default=None, description="Tool call for 'tool_use' events"
    )
