"""Agent runner models for Agent Hub client."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentRunRequest(BaseModel):
    """Request to run an agent on a task."""

    task: str = Field(..., description="Task description for the agent")
    provider: Literal["claude", "gemini"] = Field(
        default="claude", description="LLM provider"
    )
    model: str | None = Field(default=None, description="Model override")
    system_prompt: str | None = Field(default=None, description="Custom system prompt")
    temperature: float = Field(default=1.0, ge=0, le=2)
    max_turns: int = Field(default=20, ge=1, le=50, description="Maximum agentic turns")
    budget_tokens: int | None = Field(
        default=None, description="Extended thinking budget (Claude only)"
    )
    enable_code_execution: bool = Field(
        default=True, description="Enable code execution sandbox (Claude only)"
    )
    container_id: str | None = Field(
        default=None, description="Reuse existing container (Claude only)"
    )
    timeout_seconds: float = Field(default=300.0, ge=1, le=3600)


class AgentProgress(BaseModel):
    """Progress update from agent execution."""

    turn: int = Field(..., description="Current turn number")
    status: str = Field(
        ..., description="Progress status: running, tool_use, thinking, complete, error"
    )
    message: str = Field(..., description="Human-readable progress message")
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    thinking: str | None = Field(default=None)


class AgentRunResponse(BaseModel):
    """Response from agent execution."""

    agent_id: str = Field(..., description="Unique agent execution ID")
    status: str = Field(..., description="Final status: success, error, max_turns")
    content: str = Field(..., description="Agent's final response content")
    provider: str = Field(..., description="Provider used")
    model: str = Field(..., description="Model used")
    turns: int = Field(..., description="Total turns executed")
    input_tokens: int = Field(..., description="Total input tokens")
    output_tokens: int = Field(..., description="Total output tokens")
    thinking_tokens: int = Field(default=0, description="Thinking tokens (Claude only)")
    tool_calls_count: int = Field(default=0, description="Total tool calls made")
    error: str | None = Field(default=None, description="Error message if failed")
    progress_log: list[AgentProgress] = Field(
        default_factory=list, description="Execution progress log"
    )
    container_id: str | None = Field(
        default=None, description="Container ID for continuity (Claude only)"
    )
    trace_id: str | None = Field(default=None, description="Telemetry trace ID")
    session_id: str | None = Field(
        default=None, description="Agent Hub session ID for this execution"
    )
    memory_uuids: list[str] = Field(
        default_factory=list,
        description="Memory episode UUIDs loaded for this execution",
    )
    cited_uuids: list[str] = Field(
        default_factory=list, description="Memory episode UUIDs cited by the agent"
    )
