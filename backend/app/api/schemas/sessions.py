"""Session API schemas - Request/Response models."""

from datetime import datetime

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    """Request body for creating a session."""

    session_id: str | None = Field(
        default=None,
        description="Custom session ID (e.g. from Claude Code). Generated if not provided.",
    )
    project_id: str = Field(..., description="Project identifier")
    provider: str = Field(..., description="Provider: claude or gemini")
    model: str = Field(..., description="Model identifier")
    session_type: str = Field(
        default="completion",
        description="Session type: completion, chat, roundtable, image_generation, agent, claude_code",
    )
    agent_slug: str | None = Field(
        default=None,
        description="Agent slug for agent-based sessions (optional)",
    )


class MessageResponse(BaseModel):
    """Message within a session."""

    id: str
    role: str | None
    content: str | None
    tokens: int | None
    agent_id: str | None = Field(
        default=None, description="Agent identifier for multi-agent sessions"
    )
    agent_name: str | None = Field(default=None, description="Agent display name")
    model_used: str | None = Field(
        default=None, description="Model that generated this message (for assistant messages)"
    )
    created_at: datetime


class AgentTokenBreakdown(BaseModel):
    """Token breakdown for a single agent in multi-agent sessions."""

    agent_id: str
    agent_name: str | None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    message_count: int


class ContextUsageResponse(BaseModel):
    """Context window usage for a session."""

    used_tokens: int = Field(..., description="Tokens currently in context")
    limit_tokens: int = Field(..., description="Model's context window limit")
    percent_used: float = Field(..., description="Percentage of context used")
    remaining_tokens: int = Field(..., description="Tokens available")
    warning: str | None = Field(default=None, description="Warning if approaching limit")


class SessionResponse(BaseModel):
    """Response body for session operations."""

    id: str
    project_id: str
    provider: str
    model: str
    status: str
    agent_slug: str | None = Field(default=None, description="Agent that processed this session")
    session_type: str = Field(default="completion", description="Session type")
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponse] = Field(default_factory=list)
    context_usage: ContextUsageResponse | None = Field(
        default=None, description="Context window usage"
    )
    agent_token_breakdown: list[AgentTokenBreakdown] = Field(
        default_factory=list, description="Token breakdown by agent for multi-agent sessions"
    )
    total_input_tokens: int = Field(default=0, description="Total input tokens")
    total_output_tokens: int = Field(default=0, description="Total output tokens")


class SessionListItem(BaseModel):
    """Session item in list response."""

    id: str
    project_id: str
    provider: str
    model: str
    status: str
    agent_slug: str | None = Field(default=None, description="Agent that processed this session")
    session_type: str = Field(default="completion", description="Session type")
    message_count: int
    total_input_tokens: int = Field(default=0, description="Total input tokens")
    total_output_tokens: int = Field(default=0, description="Total output tokens")
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    """Response body for listing sessions."""

    sessions: list[SessionListItem]
    total: int
    page: int
    page_size: int


class CloseSessionResponse(BaseModel):
    """Response body for session close."""

    id: str = Field(..., description="Session ID")
    status: str = Field(..., description="New session status")
    message: str = Field(..., description="Status message")


class SessionForkRequest(BaseModel):
    """Request body for forking a session."""

    fork_at_turn: int | None = Field(
        default=None,
        description="Turn number to fork at. If None, forks at current state.",
    )


class SessionForkResponse(BaseModel):
    """Response body for session fork."""

    id: str = Field(..., description="New forked session ID")
    parent_session_id: str = Field(..., description="Parent session ID")
    fork_point_turn: int = Field(..., description="Turn number where fork occurred")
    message_count: int = Field(..., description="Number of messages copied")
    branch_status: str = Field(..., description="Branch status (active)")


class SessionPromoteRequest(BaseModel):
    """Request body for promoting a branch."""

    discard_siblings: bool = Field(
        default=True,
        description="Whether to mark sibling branches as discarded",
    )


class SessionPromoteResponse(BaseModel):
    """Response body for session promotion."""

    id: str = Field(..., description="Promoted session ID")
    branch_status: str = Field(..., description="New branch status (promoted)")
    discarded_siblings: list[str] = Field(
        default_factory=list,
        description="IDs of sibling branches that were discarded",
    )
    patches_applied: int = Field(
        default=0,
        description="Number of pending patches applied",
    )


class SessionEventResponse(BaseModel):
    """Single event in session timeline for full observability."""

    id: str = Field(..., description="Event UUID")
    turn: int = Field(..., description="Turn number (conversation round)")
    sequence: int = Field(..., description="Sequence within turn")
    event_type: str = Field(
        ...,
        description="Event type: user_message, assistant_message, system_message, thinking, tool_use, tool_result, memory_inject, memory_cite, error",
    )
    role: str | None = Field(default=None, description="Message role (user/assistant/system)")
    content: str | None = Field(default=None, description="Text content")
    tool_name: str | None = Field(default=None, description="Tool name for tool_use/tool_result")
    tool_input: dict[str, object] | None = Field(default=None, description="Tool input parameters")
    tool_output: dict[str, object] | None = Field(default=None, description="Tool execution result")
    tokens: int | None = Field(default=None, description="Token count")
    duration_ms: int | None = Field(default=None, description="Execution duration in ms")
    model_used: str | None = Field(default=None, description="Model that generated this event")
    agent_id: str | None = Field(default=None, description="Agent identifier")
    agent_name: str | None = Field(default=None, description="Agent display name")
    created_at: datetime = Field(..., description="Event timestamp")


class SessionEventsResponse(BaseModel):
    """Response body for session events endpoint."""

    session_id: str = Field(..., description="Session ID")
    events: list[SessionEventResponse] = Field(default_factory=list)
    total: int = Field(..., description="Total number of events")
    max_turn: int = Field(..., description="Highest turn number in session")
