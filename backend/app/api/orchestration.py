"""Orchestration API routes - Multi-agent execution endpoints.

Provides HTTP endpoints for:
- Subagent spawning
- Parallel execution
- Maker-checker verification
- Roundtable collaboration
"""

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.orchestration import (
    CodeReviewPattern,
    MakerChecker,
    ParallelExecutor,
    ParallelTask,
    SubagentConfig,
    SubagentManager,
    get_roundtable_service,
)
from app.services.telemetry import get_current_trace_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orchestration", tags=["orchestration"])


# ========== Request/Response Models ==========


class SubagentRequest(BaseModel):
    """Request to spawn a subagent."""

    task: str = Field(..., description="Task description for the subagent")
    name: str = Field(default="subagent", description="Subagent name")
    provider: Literal["claude", "gemini"] = Field(
        default="claude", description="LLM provider"
    )
    model: str | None = Field(default=None, description="Model override")
    system_prompt: str | None = Field(default=None, description="Custom system prompt")
    max_tokens: int = Field(default=4096, ge=1, le=128000)
    temperature: float = Field(default=1.0, ge=0, le=2)
    budget_tokens: int | None = Field(
        default=None, description="Extended thinking budget (Claude only)"
    )
    timeout_seconds: float = Field(default=300.0, ge=1, le=3600)


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
    max_tokens: int = 4096
    temperature: float = 1.0


class ParallelRequest(BaseModel):
    """Request for parallel subagent execution."""

    tasks: list[ParallelTaskRequest] = Field(
        ..., min_length=1, max_length=20, description="Tasks to execute in parallel"
    )
    overall_timeout: float | None = Field(
        default=None, description="Overall timeout in seconds"
    )
    fail_fast: bool = Field(
        default=False, description="Cancel remaining tasks on first failure"
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


class RoundtableCreateRequest(BaseModel):
    """Request to create a roundtable session."""

    project_id: str = Field(..., description="Project identifier")
    mode: Literal["quick", "deliberation"] = Field(
        default="quick", description="Collaboration mode"
    )
    tools_enabled: bool = Field(default=True)


class RoundtableSessionResponse(BaseModel):
    """Roundtable session info."""

    id: str
    project_id: str
    mode: str
    message_count: int
    total_tokens: int
    trace_id: str | None = None


class RoundtableMessageRequest(BaseModel):
    """Request to send a message in roundtable."""

    message: str = Field(..., description="Message content")
    target: Literal["claude", "gemini", "both"] = Field(
        default="both", description="Target agent(s)"
    )


class RoundtableDeliberateRequest(BaseModel):
    """Request for deliberation."""

    topic: str = Field(..., description="Topic to deliberate on")
    max_rounds: int = Field(default=3, ge=1, le=10)


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
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        budget_tokens=request.budget_tokens,
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
                max_tokens=t.max_tokens,
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


# ========== Roundtable Endpoints ==========


@router.post("/roundtable", response_model=RoundtableSessionResponse)
async def create_roundtable(
    request: RoundtableCreateRequest,
) -> RoundtableSessionResponse:
    """
    Create a new roundtable collaboration session.

    Returns session ID for subsequent operations.
    """
    service = get_roundtable_service()

    session = service.create_session(
        project_id=request.project_id,
        mode=request.mode,
        tools_enabled=request.tools_enabled,
    )

    return RoundtableSessionResponse(
        id=session.id,
        project_id=session.project_id,
        mode=session.mode,
        message_count=len(session.messages),
        total_tokens=session.total_tokens,
        trace_id=session.trace_id,
    )


@router.get("/roundtable/{session_id}", response_model=RoundtableSessionResponse)
async def get_roundtable(session_id: str) -> RoundtableSessionResponse:
    """Get roundtable session info."""
    service = get_roundtable_service()
    session = service.get_session(session_id)

    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    return RoundtableSessionResponse(
        id=session.id,
        project_id=session.project_id,
        mode=session.mode,
        message_count=len(session.messages),
        total_tokens=session.total_tokens,
        trace_id=session.trace_id,
    )


@router.delete("/roundtable/{session_id}")
async def end_roundtable(session_id: str) -> dict[str, Any]:
    """End a roundtable session and get summary."""
    service = get_roundtable_service()
    session = service.get_session(session_id)

    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    summary = service.end_session(session)
    return summary


@router.get("/health")
async def orchestration_health() -> dict[str, Any]:
    """Check orchestration services health."""
    roundtable = get_roundtable_service()

    return {
        "status": "healthy",
        "services": {
            "subagent_manager": True,
            "parallel_executor": True,
            "maker_checker": True,
            "roundtable": True,
        },
        "active_roundtable_sessions": len(roundtable._sessions),
    }
