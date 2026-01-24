"""Orchestration API routes - Multi-agent execution endpoints.

Provides HTTP endpoints for:
- Subagent spawning
- Parallel execution
- Maker-checker verification
- Roundtable collaboration (including WebSocket streaming)
"""

import json
import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

# max_tokens no longer has default - models auto-determine output length
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
    provider: Literal["claude", "gemini"] = Field(default="claude", description="LLM provider")
    model: str | None = Field(default=None, description="Model override")
    system_prompt: str | None = Field(default=None, description="Custom system prompt")
    max_tokens: int | None = Field(default=None, description="Max output tokens (None = model default)")
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
    max_tokens: int | None = None
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
    use_memory: bool = Field(default=True, description="Inject memory context into prompts")


class RoundtableAgentMessage(BaseModel):
    """A message from an agent in a roundtable session."""

    id: int
    role: str  # user, assistant, system
    agent_type: str | None  # claude, gemini
    content: str
    tokens: int | None
    model: str | None
    created_at: str


class RoundtableMessageResponse(BaseModel):
    """Response from sending a roundtable message."""

    session_id: str
    messages: list[RoundtableAgentMessage]
    speaker_order: list[str]  # Order agents responded: ["claude", "gemini"] or ["gemini", "claude"]
    total_tokens: int
    trace_id: str | None = None


class RoundtableDeliberateRequest(BaseModel):
    """Request for deliberation."""

    topic: str = Field(..., description="Topic to deliberate on")
    max_rounds: int = Field(default=3, ge=1, le=10)


class AgentRunRequest(BaseModel):
    """Request to run an agent on a task."""

    task: str = Field(..., description="Task description for the agent")
    provider: Literal["claude", "gemini"] = Field(default="claude", description="LLM provider")
    model: str | None = Field(default=None, description="Model override")
    system_prompt: str | None = Field(default=None, description="Custom system prompt")
    max_tokens: int = Field(default=64000, ge=1, le=128000)
    temperature: float = Field(default=1.0, ge=0, le=2)
    max_turns: int = Field(default=20, ge=1, le=50, description="Maximum agentic turns")
    # Claude-specific
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
    session_id: str  # Session ID for tracking and cancellation
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
    Memory context is automatically injected from the knowledge graph.
    """
    service = get_roundtable_service()

    session = await service.create_session(
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


@router.post("/roundtable/{session_id}/message", response_model=RoundtableMessageResponse)
async def send_roundtable_message(
    session_id: str,
    request: RoundtableMessageRequest,
) -> RoundtableMessageResponse:
    """
    Send a message to a roundtable session and get responses from agents.

    Uses sequential cascade architecture: first agent responds, then second agent
    sees the first response and provides a different perspective.

    Speaker order is randomized per volley to prevent bias.
    """
    import random

    from app.services.telemetry import get_current_trace_id

    service = get_roundtable_service()
    session = service.get_session(session_id)

    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    trace_id = get_current_trace_id()

    # Randomize speaker order for this volley (decision d2)
    agents: list[str] = ["claude", "gemini"]
    if request.target == "both":
        random.shuffle(agents)
        speaker_order = agents.copy()
    else:
        speaker_order = [request.target]

    # Collect messages generated during this volley
    new_messages: list[RoundtableAgentMessage] = []
    total_tokens = 0

    # Stream responses and collect results
    async for event in service.route_message(session, request.message, request.target):
        if event.type == "message" and event.content == "" and event.tokens > 0:
            # Message complete signal - find the most recent message for this agent
            for msg in reversed(session.messages):
                if msg.role == event.agent:
                    new_messages.append(
                        RoundtableAgentMessage(
                            id=len(new_messages) + 1,
                            role="assistant",
                            agent_type=msg.role,
                            content=msg.content,
                            tokens=msg.tokens_used,
                            model=msg.model,
                            created_at=msg.timestamp.isoformat(),
                        )
                    )
                    total_tokens += event.tokens
                    break
        elif event.type == "error":
            logger.error(f"Roundtable error from {event.agent}: {event.error}")
            raise HTTPException(
                status_code=500,
                detail=f"Agent {event.agent} error: {event.error}",
            )

    return RoundtableMessageResponse(
        session_id=session_id,
        messages=new_messages,
        speaker_order=speaker_order,
        total_tokens=total_tokens,
        trace_id=trace_id,
    )


@router.delete("/roundtable/{session_id}")
async def end_roundtable(session_id: str, store_to_memory: bool = True) -> dict[str, Any]:
    """End a roundtable session, store to memory, and get summary."""
    service = get_roundtable_service()
    session = service.get_session(session_id)

    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    summary = await service.end_session(session, store_to_memory=store_to_memory)
    return summary


@router.websocket("/roundtable/{session_id}/ws")
async def roundtable_websocket(websocket: WebSocket, session_id: str) -> None:
    """
    WebSocket endpoint for streaming roundtable responses.

    Protocol:
    1. Client connects to /api/orchestration/roundtable/{session_id}/ws
    2. Server accepts connection and sends: {"type": "connected", "session_id": "..."}
    3. Client sends message: {"type": "message", "content": "...", "target": "both"|"claude"|"gemini"}
    4. Server streams responses with agent attribution:
       - {"type": "chunk", "agent": "claude"|"gemini", "content": "..."}
       - {"type": "thinking", "agent": "claude", "content": "..."}  # Claude thinking
       - {"type": "message_complete", "agent": "claude"|"gemini", "tokens": 123}
       - {"type": "volley_complete", "speaker_order": ["claude", "gemini"], "total_tokens": 456}
    5. Client can request another round: {"type": "continue"}
       Server responds with another volley (agents discuss without new user input)
    6. Client disconnects or sends: {"type": "close"}
    """
    import random

    await websocket.accept()
    logger.info(f"Roundtable WebSocket connected for session {session_id}")

    service = get_roundtable_service()
    session = service.get_session(session_id)

    if session is None:
        await websocket.send_json({"type": "error", "message": f"Session {session_id} not found"})
        await websocket.close(code=4404)
        return

    await websocket.send_json({"type": "connected", "session_id": session_id})

    try:
        while True:
            raw_data = await websocket.receive_text()

            try:
                data = json.loads(raw_data)
                msg_type = data.get("type")

                if msg_type == "message":
                    content = data.get("content", "")
                    target = data.get("target", "both")

                    if not content:
                        await websocket.send_json(
                            {"type": "error", "message": "Message content required"}
                        )
                        continue

                    # Determine speaker order (randomized per decision d2)
                    if target == "both":
                        agents = ["claude", "gemini"]
                        random.shuffle(agents)
                        speaker_order = agents.copy()
                    else:
                        speaker_order = [target]

                    total_tokens = 0

                    # Stream responses from agents
                    async for event in service.route_message(
                        session, content, target, speaker_order=speaker_order
                    ):
                        if event.type == "message":
                            if event.content:
                                await websocket.send_json(
                                    {
                                        "type": "chunk",
                                        "agent": event.agent,
                                        "content": event.content,
                                    }
                                )
                            elif event.tokens > 0:
                                # Empty content with tokens = message complete signal
                                await websocket.send_json(
                                    {
                                        "type": "message_complete",
                                        "agent": event.agent,
                                        "tokens": event.tokens,
                                    }
                                )
                                total_tokens += event.tokens
                        elif event.type == "thinking":
                            await websocket.send_json(
                                {
                                    "type": "thinking",
                                    "agent": event.agent,
                                    "content": event.content,
                                }
                            )
                        elif event.type == "error":
                            await websocket.send_json(
                                {
                                    "type": "error",
                                    "agent": event.agent,
                                    "message": event.error,
                                }
                            )
                        elif event.type == "done":
                            await websocket.send_json(
                                {
                                    "type": "volley_complete",
                                    "speaker_order": speaker_order,
                                    "total_tokens": total_tokens,
                                }
                            )

                elif msg_type == "continue":
                    # Agents discuss further without new user input
                    continue_prompt = (
                        "Please continue the discussion, building on what was said. "
                        "Add new insights or respectfully challenge the other perspective."
                    )

                    agents = ["claude", "gemini"]
                    random.shuffle(agents)
                    speaker_order = agents.copy()
                    total_tokens = 0

                    async for event in service.route_message(
                        session, continue_prompt, "both", speaker_order=speaker_order
                    ):
                        if event.type == "message":
                            if event.content:
                                await websocket.send_json(
                                    {
                                        "type": "chunk",
                                        "agent": event.agent,
                                        "content": event.content,
                                    }
                                )
                            elif event.tokens > 0:
                                await websocket.send_json(
                                    {
                                        "type": "message_complete",
                                        "agent": event.agent,
                                        "tokens": event.tokens,
                                    }
                                )
                                total_tokens += event.tokens
                        elif event.type == "thinking":
                            await websocket.send_json(
                                {
                                    "type": "thinking",
                                    "agent": event.agent,
                                    "content": event.content,
                                }
                            )
                        elif event.type == "error":
                            await websocket.send_json(
                                {
                                    "type": "error",
                                    "agent": event.agent,
                                    "message": event.error,
                                }
                            )
                        elif event.type == "done":
                            await websocket.send_json(
                                {
                                    "type": "volley_complete",
                                    "speaker_order": speaker_order,
                                    "total_tokens": total_tokens,
                                }
                            )

                elif msg_type == "close":
                    await websocket.send_json({"type": "closed"})
                    await websocket.close(code=1000)
                    return

                else:
                    await websocket.send_json(
                        {"type": "error", "message": f"Unknown message type: {msg_type}"}
                    )

            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})

    except WebSocketDisconnect:
        logger.info(f"Roundtable WebSocket disconnected for session {session_id}")
    except Exception as e:
        logger.exception(f"Error in roundtable WebSocket: {e}")
        import contextlib

        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "error", "message": str(e)})


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
            "agent_runner": True,
        },
        "active_roundtable_sessions": len(roundtable._sessions),
    }


# ========== Agent Runner Endpoints ==========


@router.post("/run-agent", response_model=AgentRunResponse)
async def run_agent(request: AgentRunRequest) -> AgentRunResponse:
    """
    Run an agent on a task with tool execution.

    For Claude: Uses code_execution sandbox for autonomous tool calling.
    For Gemini: Uses sandboxed tool executor with bash/read/write tools (supported).

    The agent will execute in a loop, calling tools as needed until the task
    is complete or max_turns is reached.

    Returns:
        AgentRunResponse with execution results and progress log.
    """
    from app.services.agent_runner import AgentConfig, get_agent_runner

    trace_id = get_current_trace_id()
    runner = get_agent_runner()

    config = AgentConfig(
        provider=request.provider,
        model=request.model,
        system_prompt=request.system_prompt,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        max_turns=request.max_turns,
        thinking_level=request.thinking_level,
        enable_code_execution=request.enable_code_execution,
        container_id=request.container_id,
        working_dir=request.working_dir,
    )

    result = await runner.run(
        task=request.task,
        config=config,
    )

    return AgentRunResponse(
        agent_id=result.agent_id,
        session_id=result.agent_id,  # agent_id is the session tracking ID
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
    )
