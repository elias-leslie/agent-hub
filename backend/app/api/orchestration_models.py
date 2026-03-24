"""Orchestration API request/response models."""

from typing import Any

from pydantic import BaseModel, Field

from app.adapters.registry import ValidProvider

# ========== Subagent Models ==========


class SubagentRequest(BaseModel):
    """Request to spawn a subagent."""

    task: str = Field(..., description="Task description for the subagent")
    name: str = Field(default="subagent", description="Subagent name")
    provider: ValidProvider = Field(default="claude", description="LLM provider")
    model: str | None = Field(default=None, description="Model override")
    system_prompt: str | None = Field(default=None, description="Custom system prompt")
    temperature: float = Field(default=1.0, ge=0, le=2)
    thinking_level: str | None = Field(
        default=None,
        pattern="^(minimal|low|medium|high|ultrathink)$",
        description="Thinking depth: minimal/low/medium/high/ultrathink",
    )
    timeout_seconds: float | None = Field(default=None, ge=1, le=3600)
    agent_slug: str | None = Field(
        default=None,
        description="Agent slug for agent-based execution (optional)",
    )
    max_spawn_depth: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum nesting depth for subagent spawning",
    )
    current_depth: int = Field(
        default=0,
        ge=0,
        description="Current depth in spawn hierarchy (set by system)",
    )
    parent_session_id: str | None = Field(
        default=None,
        description="Parent session ID for announce-back routing. "
        "When set, the subagent result is stored as an event in the parent session.",
    )
    project_id: str | None = Field(
        default=None,
        description="Project ID for cost tracking. When set, token usage is logged.",
    )


class SubagentResponse(BaseModel):
    """Response from subagent execution."""

    subagent_id: str
    name: str
    content: str
    status: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    thinking_content: str | None = None
    thinking_tokens: int | None = None
    error: str | None = None
    trace_id: str | None = None


# ========== Parallel Execution Models ==========


class ParallelTaskRequest(BaseModel):
    """Single task in a parallel execution request."""

    task: str = Field(..., description="Task description")
    name: str = Field(default="task", description="Task name")
    provider: ValidProvider = Field(default="claude")
    model: str | None = None
    system_prompt: str | None = None
    temperature: float = 1.0


class ParallelRequest(BaseModel):
    """Request for parallel subagent execution."""

    tasks: list[ParallelTaskRequest] = Field(
        ..., min_length=1, max_length=20, description="Tasks to execute in parallel"
    )
    overall_timeout: float | None = Field(default=None, description="Overall timeout in seconds")
    fail_fast: bool = Field(default=False, description="Cancel remaining tasks on first failure")
    max_concurrency: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description="Max concurrent tasks. Overrides agent/global default.",
    )
    parent_session_id: str | None = Field(
        default=None, description="Parent session ID for announce-back routing"
    )
    project_id: str | None = Field(
        default=None,
        description="Project ID for cost tracking. When set, token usage is logged.",
    )


class ParallelResponse(BaseModel):
    """Response from parallel execution."""

    status: str
    results: list[SubagentResponse]
    total_input_tokens: int
    total_output_tokens: int
    completed_count: int
    failed_count: int
    trace_id: str | None = None


# ========== Maker-Checker Models ==========


class MakerCheckerRequest(BaseModel):
    """Request for maker-checker verification."""

    task: str = Field(..., description="Task for the maker agent")
    maker_provider: ValidProvider = Field(
        default="claude", description="Provider for maker"
    )
    checker_provider: ValidProvider = Field(
        default="gemini", description="Provider for checker"
    )
    max_iterations: int = Field(default=3, ge=1, le=5)
    project_id: str | None = Field(
        default=None,
        description="Project ID for cost tracking. When set, token usage is logged.",
    )


class MakerCheckerResponse(BaseModel):
    """Response from maker-checker verification."""

    approved: bool
    confidence: float
    final_output: str
    iterations: int
    issues: list[str]
    suggestions: list[str]
    trace_id: str | None = None


class CodeReviewRequest(BaseModel):
    """Request for code review (specialized maker-checker)."""

    task: str = Field(..., description="Code generation task")
    maker_provider: ValidProvider = Field(
        default="claude", description="Provider for code generation"
    )
    checker_provider: ValidProvider = Field(
        default="gemini", description="Provider for code review"
    )
    project_id: str | None = Field(
        default=None,
        description="Project ID for cost tracking. When set, token usage is logged.",
    )


# ========== Chain Execution Models ==========


class ChainStepRequest(BaseModel):
    """Single step in a chain execution request."""

    task: str = Field(
        ...,
        description="Task description. Use {previous} to inject prior step output.",
    )
    name: str = Field(default="step", description="Step name")
    provider: ValidProvider = Field(default="claude")
    model: str | None = None
    system_prompt: str | None = None
    temperature: float = 1.0


class ChainRequest(BaseModel):
    """Request for sequential chain execution."""

    steps: list[ChainStepRequest] = Field(
        ..., min_length=1, max_length=20, description="Steps to execute sequentially"
    )
    overall_timeout: float | None = Field(
        default=None, description="Overall timeout in seconds"
    )
    stop_on_error: bool = Field(
        default=True, description="Stop chain on first step failure"
    )
    parent_session_id: str | None = Field(
        default=None, description="Parent session ID for announce-back routing"
    )
    project_id: str | None = Field(
        default=None,
        description="Project ID for cost tracking. When set, token usage is logged.",
    )


class ChainResponse(BaseModel):
    """Response from chain execution."""

    status: str
    results: list[SubagentResponse]
    final_output: str
    total_input_tokens: int
    total_output_tokens: int
    steps_completed: int
    steps_total: int
    trace_id: str | None = None


# ========== Agent Progress Model ==========
# Note: AgentRunRequest and AgentRunResponse were removed when /run-agent was
# consolidated into /complete with agentic mode. AgentProgressInfo is still
# used by CompletionResponse for agentic execution progress.


class AgentProgressInfo(BaseModel):
    """Progress update from agentic execution."""

    turn: int
    status: str
    message: str
    tool_calls: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    thinking: str | None = None
