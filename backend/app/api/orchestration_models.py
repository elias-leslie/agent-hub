"""Orchestration API request/response models."""

from typing import Any, Literal

from pydantic import BaseModel, Field

# ========== Subagent Models ==========


class SubagentRequest(BaseModel):
    """Request to spawn a subagent."""

    task: str = Field(..., description="Task description for the subagent")
    name: str = Field(default="subagent", description="Subagent name")
    provider: Literal["claude", "gemini"] = Field(default="claude", description="LLM provider")
    model: str | None = Field(default=None, description="Model override")
    system_prompt: str | None = Field(default=None, description="Custom system prompt")
    temperature: float = Field(default=1.0, ge=0, le=2)
    thinking_level: str | None = Field(
        default=None,
        pattern="^(minimal|low|medium|high|ultrathink)$",
        description="Thinking depth: minimal/low/medium/high/ultrathink",
    )
    timeout_seconds: float = Field(default=300.0, ge=1, le=3600)
    agent_slug: str | None = Field(
        default=None,
        description="Agent slug for agent-based execution (optional)",
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
    provider: Literal["claude", "gemini"] = Field(default="claude")
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
    maker_provider: Literal["claude", "gemini"] = Field(
        default="claude", description="Provider for maker"
    )
    checker_provider: Literal["claude", "gemini"] = Field(
        default="gemini", description="Provider for checker"
    )
    max_iterations: int = Field(default=3, ge=1, le=5)


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
    maker_provider: Literal["claude", "gemini"] = Field(
        default="claude", description="Provider for code generation"
    )
    checker_provider: Literal["claude", "gemini"] = Field(
        default="gemini", description="Provider for code review"
    )


# ========== Agent Runner Models ==========


class AgentRunRequest(BaseModel):
    """Request to run an agent on a task."""

    task: str = Field(..., description="Task description for the agent")
    agent_slug: str | None = Field(
        default=None,
        description="Agent slug for agent-based routing (e.g., 'coder', 'worker'). "
        "When provided, loads agent config including model, mandates, and fallbacks.",
    )
    provider: Literal["claude", "gemini"] = Field(default="claude", description="LLM provider")
    model: str | None = Field(default=None, description="Model override")
    system_prompt: str | None = Field(default=None, description="Custom system prompt")
    temperature: float = Field(default=1.0, ge=0, le=2)
    max_turns: int = Field(default=20, ge=1, le=50, description="Maximum agentic turns")
    thinking_level: str | None = Field(
        default=None,
        pattern="^(minimal|low|medium|high|ultrathink)$",
        description="Thinking depth: minimal/low/medium/high/ultrathink",
    )
    enable_code_execution: bool = Field(
        default=True, description="Enable code execution sandbox (Claude only)"
    )
    container_id: str | None = Field(
        default=None, description="Reuse existing container (Claude only)"
    )
    working_dir: str | None = Field(
        default=None, description="Working directory for agent execution"
    )
    timeout_seconds: float = Field(default=300.0, ge=1, le=3600)
    project_id: str = Field(default="agent-hub", description="Project ID for session tracking")
    use_memory: bool = Field(default=True, description="Inject memory context on first turn")
    memory_group_id: str | None = Field(
        default=None, description="Memory group ID for isolation (defaults to project_id)"
    )


class AgentProgressInfo(BaseModel):
    """Progress update from agent execution."""

    turn: int
    status: str
    message: str
    tool_calls: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    thinking: str | None = None


class AgentRunResponse(BaseModel):
    """Response from agent execution."""

    agent_id: str
    session_id: str | None = Field(
        default=None, description="Real DB session ID for tracking (not agent_id)"
    )
    status: str  # "success", "error", "max_turns"
    content: str
    provider: str
    model: str
    turns: int
    input_tokens: int
    output_tokens: int
    thinking_tokens: int = 0
    tool_calls_count: int = 0
    error: str | None = None
    progress_log: list[AgentProgressInfo] = []
    container_id: str | None = None
    trace_id: str | None = None
    memory_uuids: list[str] = Field(
        default_factory=list, description="UUIDs of memory items loaded/injected"
    )
    cited_uuids: list[str] = Field(
        default_factory=list, description="UUIDs of memory items referenced in response"
    )
