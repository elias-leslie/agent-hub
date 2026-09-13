"""Request schemas for completion API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.constants.agent_limits import DEFAULT_AGENTIC_MAX_TURNS as DEFAULT_AGENTIC_MAX_TURNS
from app.models.field_lengths import EXTERNAL_ID_MAX_LENGTH


class MessageInput(BaseModel):
    """Input message in conversation.

    Content can be:
    - str: Simple text content
    - list[dict]: Typed content blocks (text, image, or audio)

    Binary image/audio block format:
    {
        "type": "image" | "audio",
        "source": {
            "type": "base64",
            "media_type": "image/png" | "audio/wav",
            "data": "<base64-encoded-data>"
        }
    }
    """

    role: str = Field(..., max_length=20, description="Message role: user, assistant, or system")
    content: str | list[dict[str, Any]] = Field(
        ..., description="Message content - string or list of content blocks"
    )


class ToolDefinition(BaseModel):
    """Tool definition for model to call."""

    name: str = Field(..., max_length=100, description="Tool name")
    description: str = Field(..., max_length=5000, description="Tool description")
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


class SourceMetadata(BaseModel):
    """Per-event source metadata for transport/surface continuity."""

    transport: str | None = Field(default=None, max_length=50)
    surface: str | None = Field(default=None, max_length=100)
    chat_id: str | None = Field(default=None, max_length=100)
    message_id: str | None = Field(default=None, max_length=100)
    pane_id: str | None = Field(default=None, max_length=100)
    source_client: str | None = Field(default=None, max_length=100)


class WorkContext(BaseModel):
    """First-class work context injected into agent prompt context."""

    mode: str = Field(default="general", max_length=50)
    preferred_agent_slug: str | None = Field(default=None, max_length=100)
    explore_policy: str | None = Field(default=None, max_length=20)
    research_policy: str | None = Field(default=None, max_length=20)
    verifier_enabled: bool | None = None
    project_id: str | None = Field(default=None, max_length=100)
    project_name: str | None = Field(default=None, max_length=200)
    task_id: str | None = Field(default=None, max_length=100)
    task_title: str | None = Field(default=None, max_length=500)
    task_summary: str | None = Field(default=None, max_length=5000)
    feedback_id: str | None = Field(default=None, max_length=100)
    design_id: str | None = Field(default=None, max_length=100)
    artifact_summary: str | None = Field(default=None, max_length=5000)
    surface: str | None = Field(default=None, max_length=100)
    pane_id: str | None = Field(default=None, max_length=100)


class NativeContinuationRequest(BaseModel):
    """Explicit delta-context contract for a retained Codex native thread."""

    mode: Literal["snapshot", "delta"]
    generation: int = Field(..., ge=1)
    request_id: str = Field(..., min_length=1, max_length=100)
    expected_turn: int = Field(..., ge=0)
    context_version: str = Field(..., min_length=1, max_length=100)
    role: Literal["hunter", "reviewer"]
    controller_generation: str = Field(..., min_length=1, max_length=100)
    instruction_hash: str | None = Field(
        default=None,
        pattern="^[0-9a-f]{64}$",
        description="Instruction hash returned by the snapshot turn; required for deltas.",
    )
    tool_policy_hash: str | None = Field(
        default=None,
        pattern="^[0-9a-f]{64}$",
        description="Tool-policy hash returned by the snapshot turn; required for deltas.",
    )
    reasoning_effort: Literal["low", "medium", "high", "xhigh", "max", "ultra"] = "xhigh"
    cyber_access_program: Literal["standard"] | None = Field(
        default=None,
        description=(
            "Optional native cyber-access request. This requests provider treatment but does "
            "not assert entitlement or observed delivery."
        ),
    )
    close_after: bool = False

    @model_validator(mode="after")
    def _validate_continuation(self) -> NativeContinuationRequest:
        if self.mode == "snapshot" and self.expected_turn != 0:
            raise ValueError("Snapshot continuation requires expected_turn=0.")
        if self.mode == "delta" and self.expected_turn == 0:
            raise ValueError("Delta continuation requires expected_turn greater than zero.")
        if self.mode == "delta" and (not self.instruction_hash or not self.tool_policy_hash):
            raise ValueError("Delta continuation requires instruction_hash and tool_policy_hash.")
        if self.role == "reviewer" and (
            self.mode != "snapshot" or self.expected_turn != 0 or not self.close_after
        ):
            raise ValueError("Reviewer native turns must be fresh snapshots with close_after=true.")
        return self


class NativeContinuationCloseRequest(BaseModel):
    """Close one exact retained native generation."""

    session_id: str = Field(..., min_length=1, max_length=100)
    generation: int = Field(..., ge=1)
    controller_generation: str = Field(..., min_length=1, max_length=100)


class CompletionRequest(BaseModel):
    """Request body for completion endpoint."""

    model: str | None = Field(
        default=None,
        description="Optional catalog model override for the required agent_slug. Omit for canonical agent routing. Conflicting @mentions are rejected.",
    )
    messages: list[MessageInput] = Field(..., description="Conversation messages")
    system_prompt: str | None = Field(default=None, description="Application instructions appended to canonical operator and agent context.")
    temperature: float = Field(default=1.0, ge=0.0, le=2.0, description="Sampling temperature")
    session_id: str | None = Field(default=None, max_length=100, description="Existing session ID to continue")
    native_continuation: NativeContinuationRequest | None = Field(
        default=None,
        description=(
            "Retained Codex native-thread contract. Snapshot sends a complete selected context; "
            "delta sends only newly recorded state. This path never prepends the stored transcript."
        ),
    )
    parent_session_id: str | None = Field(
        default=None,
        max_length=100,
        description="Optional parent session ID used to attach spawned work as a child lane.",
    )
    source_metadata: SourceMetadata | None = Field(
        default=None,
        description="Transport/surface metadata stored on persisted session events.",
    )
    work_context: WorkContext | None = Field(
        default=None,
        description="First-class project/task/artifact context injected into the model prompt.",
    )
    project_id: str = Field(..., description="Project ID for session tracking (required)")
    external_id: str | None = Field(
        default=None,
        max_length=EXTERNAL_ID_MAX_LENGTH,
        description="External ID for cost aggregation (e.g., task-123, user-456)",
    )
    enable_caching: bool = Field(default=True, description="Enable provider prompt caching when supported")
    cache_ttl: str = Field(default="ephemeral", max_length=20, description="Cache TTL: ephemeral (5min) or 1h")
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
        description="Enable provider code execution to call tools programmatically when supported",
    )
    container_id: str | None = Field(
        default=None,
        description="Container ID for provider code execution continuity when supported",
    )
    use_memory: bool = Field(
        default=True,
        description="Inject relevant context from semantic memory",
    )
    memory_group_id: str | None = Field(
        default=None,
        description="Memory group ID for isolation (defaults to project_id)",
    )
    memory_variant_override: str | None = Field(
        default=None,
        max_length=32,
        description="Optional memory injection variant override for experiments (e.g., BASELINE, MINIMAL).",
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
        max_length=100,
        description=(
            "Agent slug for routing (e.g., 'coder', 'planner'). When provided, "
            "loads agent config from database, injects mandates, and uses fallback chains."
        ),
    )
    disable_agent_fallbacks: bool = Field(
        default=False,
        description="Disable agent fallback and escalation models; require the resolved/requested model to execute directly.",
    )
    include_roles: list[str] | None = Field(
        default=None,
        description=(
            "Filter which prompt roles to inject. When provided, only agent prompt "
            "assignments with matching roles are included. When None (default), all "
            "assigned prompts are injected. Example: ['system', 'autocode']"
        ),
    )
    prompt_mode: str | None = Field(
        default=None,
        pattern="^(full|chat|none)$",
        description=(
            "Runtime prompt profile. full includes persona context; chat uses assigned "
            "prompt roles without heavyweight persona/evolution context; none disables "
            "agent prompt injection."
        ),
    )
    stream: bool = Field(
        default=False,
        description="Enable SSE streaming. Returns text/event-stream with data: {json} format.",
    )
    max_turns: int = Field(
        default=1,
        ge=1,
        description="Maximum agentic turns. 1 = single completion, >1 = agentic loop with tool execution.",
    )
    working_dir: str | None = Field(
        default=None,
        max_length=500,
        description="Working directory for tool execution (agentic mode only).",
    )
    execute_tools: bool = Field(
        default=False,
        description="Execute tool calls in an agentic loop. When True, tools are executed and results fed back.",
    )
    read_only: bool = Field(
        default=False,
        description="Mark this tool-loop run as read-only for ownership and live-lane diagnostics.",
    )
    trace_id: str | None = Field(
        default=None,
        max_length=200,
        description="Trace ID for event correlation (e.g., SummitFlow task_id). "
        "Events are published to Redis for real-time observability.",
    )
    current_branch: str | None = Field(
        default=None,
        max_length=200,
        description="Current git branch for continuity branch scoping (e.g., 'main', 'feature/auth')",
    )
    async_execution: bool = Field(
        default=False,
        description="Run agentic completion asynchronously via background worker. "
        "Returns 202 with task_id for polling. Only applies to agentic requests.",
    )

    @model_validator(mode="before")
    @classmethod
    def _apply_agentic_turn_defaults(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if not data.get("execute_tools"):
            return data
        raw_turns = data.get("max_turns")
        if raw_turns is None or raw_turns == 1:
            return {**data, "max_turns": DEFAULT_AGENTIC_MAX_TURNS}
        return data

    @model_validator(mode="after")
    def _validate_native_continuation(self) -> CompletionRequest:
        if self.native_continuation is None:
            return self
        if self.stream or self.async_execution or self.execute_tools or self.max_turns != 1:
            raise ValueError(
                "Native continuation requires a synchronous single turn with tool execution disabled."
            )
        if self.tools or self.enable_programmatic_tools or self.container_id:
            raise ValueError("Native continuation does not permit model tools or containers.")
        if self.use_memory:
            raise ValueError(
                "Native continuation requires use_memory=false; selected context belongs in the snapshot."
            )
        if len(self.messages) != 1 or self.messages[0].role != "user":
            raise ValueError("Native continuation requires exactly one user message per turn.")
        if not isinstance(self.messages[0].content, str):
            raise ValueError("Native continuation currently accepts text input only.")
        if self.native_continuation.mode == "snapshot" and not self.system_prompt:
            raise ValueError("Native continuation snapshots require system_prompt instructions.")
        if not self.session_id:
            raise ValueError(
                "Native continuation requires a caller-supplied session_id for retry safety."
            )
        if len(self.session_id) > 36:
            raise ValueError("Native continuation session_id must fit the durable session key.")
        return self


class EstimateRequest(BaseModel):
    """Request body for cost estimation endpoint."""

    model: str = Field(..., max_length=200, description="Model identifier")
    messages: list[MessageInput] = Field(..., description="Conversation messages")
