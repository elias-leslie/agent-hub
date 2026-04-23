"""Orchestration API request/response models."""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.adapters.registry import ValidProvider
from app.api.complete.request_schemas import ResponseFormat
from app.api.complete.usage_schemas import ContextUsageInfo, OutputUsageInfo, UsageInfo

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
    timeout_seconds: float | None = Field(default=None, ge=1)
    agent_slug: str | None = Field(
        default=None,
        description=(
            "Low-level single-agent execution path. For explicit clarify/plan/execute/"
            "review/qa flows, prefer /api/orchestration/workflow."
        ),
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


# ========== Committee Roundtable Models ==========


class CommitteeSeatConfig(BaseModel):
    key: str
    label: str
    enabled: bool = True
    agent_slug: str
    model_id: str | None = None
    instruction: str | None = None
    weight: float = Field(default=1.0, ge=0.0)


class CommitteeOrchestratorConfig(BaseModel):
    agent_slug: str = "investment-committee"
    model_id: str | None = None
    instruction: str | None = None


class CommitteeConfig(BaseModel):
    orchestrator: CommitteeOrchestratorConfig
    seats: list[CommitteeSeatConfig] = Field(default_factory=list)


class CommitteeRoundtableRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    window_days: int = Field(default=3, ge=1, le=30)
    source_snapshot: dict[str, Any] | str = Field(default_factory=dict)
    project_id: str = Field(default="portfolio-ai")
    agent_slug: str = Field(default="investment-committee")
    symbols: list[str] | None = None
    trace_id: str | None = None
    external_id: str | None = None


class CommitteeRoundtableResponse(BaseModel):
    agent_slug: str
    committee_config: CommitteeConfig
    committee_summary: dict[str, Any] = Field(default_factory=dict)
    calls: list[dict[str, Any]] = Field(default_factory=list)
    votes: list[dict[str, Any]] = Field(default_factory=list)


# ========== Canonical Workflow Models ==========

WorkflowStageName = Literal["clarify", "plan", "execute", "review", "qa"]
CANONICAL_WORKFLOW_STAGES: tuple[WorkflowStageName, ...] = (
    "clarify",
    "plan",
    "execute",
    "review",
    "qa",
)
CANONICAL_WORKFLOW_DEFAULT_AGENTS: dict[WorkflowStageName, str] = {
    "clarify": "chat",
    "plan": "planner",
    "execute": "coder",
    "review": "reviewer",
    "qa": "critic",
}
CANONICAL_WORKFLOW_DEFAULT_PHASES: dict[WorkflowStageName, str] = {
    "clarify": "planning",
    "plan": "planning",
    "execute": "implementation",
    "review": "review",
    "qa": "review",
}


class WorkflowStageRequest(BaseModel):
    """One explicit stage in canonical operator workflow."""

    task: str = Field(..., description="Stage-specific instructions for this workflow step")
    agent_slug: str | None = Field(
        default=None,
        description=(
            "Optional agent override. Defaults are chat=clarify, planner=plan, "
            "coder=execute, reviewer=review, critic=qa."
        ),
    )
    task_type: str | None = Field(
        default=None,
        description="Optional task type passed through to /api/complete",
    )
    phase: str | None = Field(
        default=None,
        description="Optional phase passed through to /api/complete",
    )
    include_roles: list[str] | None = Field(
        default=None,
        description="Optional prompt roles to inject for this stage",
    )
    response_format: ResponseFormat | None = Field(
        default=None,
        description="Optional structured output contract for this stage",
    )
    use_memory: bool = Field(
        default=True,
        description="Whether to inject memory context for this stage",
    )
    execute_tools: bool = Field(
        default=False,
        description="Enable direct tool execution for this stage",
    )
    max_turns: int = Field(
        default=1,
        ge=1,
        description="Maximum turn budget for this stage",
    )
    working_dir: str | None = Field(
        default=None,
        description="Optional working directory for tool-capable stages",
    )
    current_branch: str | None = Field(
        default=None,
        description="Optional git branch context for this stage",
    )
    thinking_level: str | None = Field(
        default=None,
        pattern="^(minimal|low|medium|high|ultrathink)$",
        description="Optional thinking depth override for this stage",
    )
    disable_agent_fallbacks: bool = Field(
        default=False,
        description="Disable fallback models for this stage",
    )


class WorkflowRequest(BaseModel):
    """Explicit clarify -> plan -> execute -> review -> qa workflow request."""

    project_id: str = Field(..., description="Project ID for all stages in workflow")
    parent_session_id: str | None = Field(
        default=None,
        description=(
            "Optional persona or operator session ID that should own workflow stages "
            "as child lanes."
        ),
    )
    shared_context: str | None = Field(
        default=None,
        description="Optional shared context prepended to every stage prompt",
    )
    external_id: str | None = Field(
        default=None,
        description="Optional external identifier reused across workflow stages",
    )
    trace_id: str | None = Field(
        default=None,
        description="Optional trace identifier reused across workflow stages",
    )
    clarify: WorkflowStageRequest | None = Field(default=None, description="Clarification stage")
    plan: WorkflowStageRequest | None = Field(default=None, description="Planning stage")
    execute: WorkflowStageRequest | None = Field(default=None, description="Implementation stage")
    review: WorkflowStageRequest | None = Field(default=None, description="Review stage")
    qa: WorkflowStageRequest | None = Field(default=None, description="Final QA stage")

    @model_validator(mode="after")
    def validate_has_stage(self) -> "WorkflowRequest":
        if not any(
            getattr(self, stage_name) is not None for stage_name in CANONICAL_WORKFLOW_STAGES
        ):
            raise ValueError("At least one workflow stage must be provided.")
        return self


class WorkflowStageResponse(BaseModel):
    """One completed stage in canonical workflow."""

    stage: WorkflowStageName
    agent_used: str | None = None
    content: str
    model: str
    provider: str
    session_id: str
    usage: UsageInfo
    context_usage: ContextUsageInfo | None = None
    output_usage: OutputUsageInfo | None = None
    finish_reason: str | None = None
    memory_facts_injected: int = 0
    fallback_used: bool = False
    fallback_reason: str | None = None
    cited_uuids: list[str] = Field(default_factory=list)


class WorkflowResponse(BaseModel):
    """Canonical workflow response."""

    status: str
    stages: list[WorkflowStageResponse]
    final_output: str
    total_input_tokens: int
    total_output_tokens: int


# ========== Agent Progress Model ==========
# Note: AgentRunRequest and AgentRunResponse were removed when /run-agent was
# consolidated into /complete with agentic mode. AgentProgressInfo is still
# used by CompletionResponse for agentic execution progress.


class AgentProgressInfo(BaseModel):
    """Progress update from agentic execution."""

    turn: int
    status: str
    message: str
    topic: str | None = None
    tool_calls: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    thinking: str | None = None
