"""Orchestration API routes - Multi-agent execution endpoints.

Provides HTTP endpoints for:
- Subagent spawning
- Parallel execution
- Maker-checker verification
- Agent runner (main chat functionality)
"""

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Message as DBMessage
from app.services.orchestration import (
    CodeReviewPattern,
    MakerChecker,
    ParallelExecutor,
    ParallelTask,
    SubagentConfig,
    SubagentManager,
)
from app.services.telemetry import get_current_trace_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orchestration", tags=["orchestration"])


# ========== Request/Response Models ==========


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


# ========== Singleton Managers ==========


_subagent_manager: SubagentManager | None = None
_parallel_executor: ParallelExecutor | None = None


def get_subagent_manager() -> SubagentManager:
    """Get or create subagent manager singleton."""
    global _subagent_manager
    if _subagent_manager is None:
        _subagent_manager = SubagentManager()
    return _subagent_manager


def get_parallel_executor() -> ParallelExecutor:
    """Get or create parallel executor singleton."""
    global _parallel_executor
    if _parallel_executor is None:
        _parallel_executor = ParallelExecutor()
    return _parallel_executor


# ========== Subagent Endpoints ==========


@router.post("/subagent", response_model=SubagentResponse)
async def spawn_subagent(request: SubagentRequest) -> SubagentResponse:
    """
    Spawn a subagent to handle a task.

    Creates an isolated context for the subagent with optional system prompt.
    """
    manager = get_subagent_manager()
    trace_id = get_current_trace_id()

    config = SubagentConfig(
        name=request.name,
        provider=request.provider,
        model=request.model,
        system_prompt=request.system_prompt,
        temperature=request.temperature,
        thinking_level=request.thinking_level,
        timeout_seconds=request.timeout_seconds,
    )

    result = await manager.spawn(
        task=request.task,
        config=config,
        trace_id=trace_id,
    )

    return SubagentResponse(
        subagent_id=result.subagent_id,
        name=result.name,
        content=result.content,
        status=result.status,
        provider=result.provider,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        thinking_content=result.thinking_content,
        thinking_tokens=result.thinking_tokens,
        error=result.error,
        trace_id=result.trace_id,
    )


# ========== Parallel Execution Endpoints ==========


@router.post("/parallel", response_model=ParallelResponse)
async def execute_parallel(request: ParallelRequest) -> ParallelResponse:
    """
    Execute multiple subagents in parallel.

    Supports configurable concurrency and timeout.
    """
    executor = get_parallel_executor()
    trace_id = get_current_trace_id()

    tasks = [
        ParallelTask(
            task=t.task,
            config=SubagentConfig(
                name=t.name,
                provider=t.provider,
                model=t.model,
                system_prompt=t.system_prompt,
                temperature=t.temperature,
            ),
        )
        for t in request.tasks
    ]

    result = await executor.execute(
        tasks=tasks,
        overall_timeout=request.overall_timeout,
        trace_id=trace_id,
        fail_fast=request.fail_fast,
    )

    return ParallelResponse(
        status=result.status,
        results=[
            SubagentResponse(
                subagent_id=r.subagent_id,
                name=r.name,
                content=r.content,
                status=r.status,
                provider=r.provider,
                model=r.model,
                input_tokens=r.input_tokens,
                output_tokens=r.output_tokens,
                thinking_content=r.thinking_content,
                thinking_tokens=r.thinking_tokens,
                error=r.error,
                trace_id=r.trace_id,
            )
            for r in result.results
        ],
        total_input_tokens=result.total_input_tokens,
        total_output_tokens=result.total_output_tokens,
        completed_count=result.completed_count,
        failed_count=result.failed_count,
        trace_id=result.trace_id,
    )


# ========== Maker-Checker Endpoints ==========


@router.post("/maker-checker", response_model=MakerCheckerResponse)
async def run_maker_checker(request: MakerCheckerRequest) -> MakerCheckerResponse:
    """
    Run maker-checker verification.

    Uses one agent to generate output and another to verify.
    """
    trace_id = get_current_trace_id()

    maker_config = SubagentConfig(
        name="maker",
        provider=request.maker_provider,
    )
    checker_config = SubagentConfig(
        name="checker",
        provider=request.checker_provider,
    )

    verifier = MakerChecker(
        maker_config=maker_config,
        checker_config=checker_config,
        max_iterations=request.max_iterations,
    )

    result = await verifier.verify(
        task=request.task,
        trace_id=trace_id,
    )

    return MakerCheckerResponse(
        approved=result.approved,
        confidence=result.confidence,
        final_output=result.final_output,
        iterations=result.iterations,
        issues=result.issues,
        suggestions=result.suggestions,
        trace_id=trace_id,
    )


@router.post("/code-review", response_model=MakerCheckerResponse)
async def run_code_review(request: CodeReviewRequest) -> MakerCheckerResponse:
    """
    Run code generation with code review.

    Specialized maker-checker for code tasks.
    """
    trace_id = get_current_trace_id()

    reviewer = CodeReviewPattern(
        maker_provider=request.maker_provider,
        checker_provider=request.checker_provider,
    )

    result = await reviewer.verify(
        task=request.task,
        trace_id=trace_id,
    )

    return MakerCheckerResponse(
        approved=result.approved,
        confidence=result.confidence,
        final_output=result.final_output,
        iterations=result.iterations,
        issues=result.issues,
        suggestions=result.suggestions,
        trace_id=trace_id,
    )


# ========== Health Check ==========


@router.get("/health")
async def orchestration_health() -> dict[str, Any]:
    """Check orchestration services health."""
    return {
        "status": "healthy",
        "services": {
            "subagent_manager": True,
            "parallel_executor": True,
            "maker_checker": True,
            "agent_runner": True,
        },
    }


# ========== Agent Runner Endpoints ==========


@router.post("/run-agent", response_model=AgentRunResponse)
async def run_agent(
    request: AgentRunRequest,
    http_request: Request,
    db: Annotated[AsyncSession | None, Depends(get_db)] = None,
) -> AgentRunResponse:
    """
    Run an agent on a task with tool execution.

    For Claude: Uses code_execution sandbox for autonomous tool calling.
    For Gemini: Uses sandboxed tool executor with bash/read/write tools (supported).

    The agent will execute in a loop, calling tools as needed until the task
    is complete or max_turns is reached.

    When agent_slug is provided, resolves the agent configuration and injects
    mandates into the system prompt.

    Returns:
        AgentRunResponse with execution results and progress log.
    """
    from app.services.agent_runner import AgentConfig, get_agent_runner

    trace_id = get_current_trace_id()
    runner = get_agent_runner()

    resolved_provider = request.provider
    resolved_model = request.model
    system_prompt = request.system_prompt

    if request.agent_slug:
        from app.services.agent_routing import inject_agent_mandates, resolve_agent

        if db is None:
            raise HTTPException(
                status_code=500,
                detail="Database connection required for agent routing.",
            )

        resolved_agent = await resolve_agent(request.agent_slug, db)
        resolved_provider = resolved_agent.provider
        resolved_model = request.model or resolved_agent.model

        # Set agent_slug on request.state for access control middleware logging
        http_request.state.agent_slug = request.agent_slug

        mandate_injection = await inject_agent_mandates(resolved_agent.agent, db)
        if mandate_injection.system_content:
            if system_prompt:
                system_prompt = f"{mandate_injection.system_content}\n\n{system_prompt}"
            else:
                system_prompt = mandate_injection.system_content

        logger.info(
            f"Agent routing for run_agent: {request.agent_slug} -> "
            f"{resolved_model} ({resolved_provider}), mandates={len(mandate_injection.injected_uuids)}"
        )

    config = AgentConfig(
        provider=resolved_provider,
        model=resolved_model,
        system_prompt=system_prompt,
        temperature=request.temperature,
        max_turns=request.max_turns,
        thinking_level=request.thinking_level,
        enable_code_execution=request.enable_code_execution,
        container_id=request.container_id,
        working_dir=request.working_dir,
        project_id=request.project_id,
        use_memory=request.use_memory,
        memory_group_id=request.memory_group_id,
        agent_slug=request.agent_slug,
    )

    result = await runner.run(
        task=request.task,
        config=config,
    )

    # Save messages to database for session history
    if db and result.session_id:
        # Save system message if present
        if system_prompt:
            db_msg = DBMessage(
                session_id=result.session_id,
                role="system",
                content=system_prompt,
            )
            db.add(db_msg)

        # Save user task
        db_msg = DBMessage(
            session_id=result.session_id,
            role="user",
            content=request.task,
        )
        db.add(db_msg)

        # Save assistant response
        db_msg = DBMessage(
            session_id=result.session_id,
            role="assistant",
            content=result.content,
            tokens=result.output_tokens,
            model_used=result.model,
        )
        db.add(db_msg)

        await db.commit()

    return AgentRunResponse(
        agent_id=result.agent_id,
        session_id=result.session_id,
        status=result.status,
        content=result.content,
        provider=result.provider,
        model=result.model,
        turns=result.turns,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        thinking_tokens=result.thinking_tokens,
        tool_calls_count=result.tool_calls_count,
        error=result.error,
        progress_log=[
            AgentProgressInfo(
                turn=p.turn,
                status=p.status,
                message=p.message,
                tool_calls=p.tool_calls,
                tool_results=p.tool_results,
                thinking=p.thinking,
            )
            for p in result.progress_log
        ],
        container_id=result.container_id,
        trace_id=trace_id,
        memory_uuids=result.memory_uuids,
        cited_uuids=result.cited_uuids,
    )
