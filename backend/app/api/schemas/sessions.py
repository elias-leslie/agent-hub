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
    external_id: str | None = Field(default=None, description="Linked external work item ID")
    current_branch: str | None = Field(default=None, description="Git branch at session start")
    cwd: str | None = Field(default=None, description="Working directory at session start")
    declared_scope_paths: list[str] = Field(default_factory=list)
    observed_read_paths: list[str] = Field(default_factory=list)
    observed_write_paths: list[str] = Field(default_factory=list)
    scope_confidence: str | None = Field(default=None)
    provider_metadata: dict[str, object] = Field(default_factory=dict)


class ToolExecutionResponse(BaseModel):
    """Tool execution within a message turn."""

    id: str = Field(..., description="Tool event UUID")
    name: str = Field(..., description="Tool name (e.g., Write, Edit, Bash)")
    input: dict[str, object] | None = Field(default=None, description="Tool input parameters")
    status: str = Field(default="complete", description="Execution status")
    result: str | None = Field(default=None, description="Tool output summary")
    duration_ms: int | None = Field(default=None, description="Execution duration in ms")


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
    model_display_name: str | None = Field(
        default=None, description="Human-readable model name from catalog"
    )
    agent_display_name: str | None = Field(
        default=None, description="Resolved display name for the agent (e.g. persona name)"
    )
    thinking: str | None = Field(
        default=None, description="Extended thinking content for this turn"
    )
    thinking_tokens: int | None = Field(
        default=None, description="Token count for thinking"
    )
    tool_executions: list[ToolExecutionResponse] = Field(
        default_factory=list, description="Tool executions in this turn"
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


class LiveActivityResponse(BaseModel):
    """Structured live execution state for a session."""

    phase: str
    status: str
    source: str = Field(default="runtime", description="Origin of live activity payload: runtime or fallback")
    summary: str | None = None
    health: str
    stalled: bool = False
    stall_reason: str | None = None
    quiet_for_seconds: int | None = None
    last_event_type: str | None = None
    last_event_at: str | None = None
    last_model_activity_at: str | None = None
    current_tool_name: str | None = None
    last_tool_name: str | None = None
    last_tool_started_at: str | None = None
    last_tool_finished_at: str | None = None
    last_tool_error: bool | None = None
    last_read_path: str | None = None
    last_write_path: str | None = None
    last_command: str | None = None
    last_validation_command: str | None = None
    last_command_exit_code: int | None = None
    outstanding_tool_calls: int = 0
    tool_calls_count: int = 0
    termination_reason: str | None = None
    files_touched: list[str] = Field(default_factory=list)
    last_heartbeat_at: str | None = None
    lifecycle_state: str = Field(default="idle", description="Canonical lifecycle classification")
    lifecycle_reason_codes: list[str] = Field(
        default_factory=list,
        description="Reason codes supporting the current lifecycle classification",
    )
    dead_signals: list[str] = Field(
        default_factory=list,
        description="Signals suggesting the session is no longer meaningfully live",
    )
    anti_reap_signals: list[str] = Field(
        default_factory=list,
        description="Signals that block conservative automatic reaping",
    )
    has_owner_lane: bool = Field(default=False, description="Whether an owner lane still points at this session")
    has_specialist_lane: bool = Field(default=False, description="Whether a specialist lane still points at this session")
    reapable: bool = Field(default=False, description="Whether the session is safe for conservative auto-reaping")
    reapable_reason: str | None = Field(default=None, description="Compact reason string for reapable sessions")
    status_source: str = Field(
        default="session",
        description="Authority for row status beacon: session when persisted status wins, runtime when live activity drives the beacon",
    )
    status_matches_session: bool = Field(
        default=True,
        description="Whether live runtime status matches the persisted session status",
    )


class SessionResponse(BaseModel):
    """Response body for session operations."""

    id: str
    project_id: str
    provider: str
    model: str
    requested_provider: str | None = Field(default=None, description="Originally requested provider")
    requested_model: str | None = Field(default=None, description="Originally requested model")
    effective_provider: str | None = Field(default=None, description="Provider that actually executed the session")
    effective_model: str | None = Field(default=None, description="Model that actually executed the session")
    requested_model_display_name: str | None = Field(default=None, description="Human-readable requested model name")
    effective_model_display_name: str | None = Field(default=None, description="Human-readable effective model name")
    fallback_used: bool = Field(default=False, description="Whether execution fell back away from the requested model")
    fallback_reason: str | None = Field(default=None, description="Why the primary model was abandoned, if known")
    status: str
    agent_slug: str | None = Field(default=None, description="Agent that processed this session")
    session_type: str = Field(default="completion", description="Session type")
    parent_session_id: str | None = Field(default=None, description="Parent session ID")
    external_id: str | None = Field(default=None, description="Linked external work item ID")
    client_id: str | None = Field(default=None, description="Authenticated caller client ID")
    request_source: str | None = Field(default=None, description="Request source header")
    source_client: str | None = Field(default=None, description="Logical caller identifier")
    source_path: str | None = Field(default=None, description="Caller file path")
    attribution_kind: str | None = Field(default=None, description="High-level workload classification")
    attribution_label: str | None = Field(default=None, description="UI-friendly workload classification label")
    attribution_detail: str | None = Field(default=None, description="Source string that drove the workload classification")
    current_branch: str | None = Field(default=None, description="Git branch associated with the session")
    working_dir: str | None = Field(default=None, description="Working directory captured for the session")
    repo_root: str | None = Field(default=None, description="Detected repo root for the session")
    host: str | None = Field(default=None, description="Origin host for the session")
    tmux_session_name: str | None = Field(default=None, description="tmux session name when applicable")
    tmux_pane_id: str | None = Field(default=None, description="tmux pane id when applicable")
    workstream_status: str | None = Field(default=None, description="Lane lifecycle status")
    summary_oneliner: str | None = Field(default=None, description="One-line session summary")
    child_session_count: int | None = Field(
        default=None,
        description="Count of persisted child sessions linked by parent_session_id",
    )
    active_child_session_count: int | None = Field(
        default=None,
        description="Count of child sessions currently considered active from persisted status/live activity",
    )
    batch_task_ids: list[str] = Field(default_factory=list, description="Task ids linked to a batch orchestrator session")
    declared_scope_paths: list[str] = Field(default_factory=list)
    observed_read_paths: list[str] = Field(default_factory=list)
    observed_write_paths: list[str] = Field(default_factory=list)
    scope_confidence: str | None = Field(default=None, description="declared | observed_write | observed_read | unknown")
    created_at: datetime
    updated_at: datetime
    status_source: str = Field(
        default="session",
        description="Authority for row/detail status beacon: session or runtime",
    )
    status_matches_live: bool = Field(
        default=True,
        description="Whether persisted session status matches current runtime status",
    )
    live_activity: LiveActivityResponse | None = Field(
        default=None, description="Current live execution state"
    )
    message_count: int | None = Field(
        default=None,
        description="Count of persisted user and assistant messages",
    )
    event_count: int | None = Field(
        default=None,
        description="Count of persisted session events",
    )
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
    requested_provider: str | None = Field(default=None, description="Originally requested provider")
    requested_model: str | None = Field(default=None, description="Originally requested model")
    effective_provider: str | None = Field(default=None, description="Provider that actually executed the session")
    effective_model: str | None = Field(default=None, description="Model that actually executed the session")
    requested_model_display_name: str | None = Field(default=None, description="Human-readable requested model name")
    effective_model_display_name: str | None = Field(default=None, description="Human-readable effective model name")
    fallback_used: bool = Field(default=False, description="Whether execution fell back away from the requested model")
    fallback_reason: str | None = Field(default=None, description="Why the primary model was abandoned, if known")
    status: str
    agent_slug: str | None = Field(default=None, description="Agent that processed this session")
    session_type: str = Field(default="completion", description="Session type")
    parent_session_id: str | None = Field(default=None, description="Parent session ID")
    external_id: str | None = Field(default=None, description="Linked external work item ID")
    client_id: str | None = Field(default=None, description="Authenticated caller client ID")
    request_source: str | None = Field(default=None, description="Request source header")
    source_client: str | None = Field(default=None, description="Logical caller identifier")
    source_path: str | None = Field(default=None, description="Caller file path")
    attribution_kind: str | None = Field(default=None, description="High-level workload classification")
    attribution_label: str | None = Field(default=None, description="UI-friendly workload classification label")
    attribution_detail: str | None = Field(default=None, description="Source string that drove the workload classification")
    current_branch: str | None = Field(default=None, description="Git branch associated with the session")
    working_dir: str | None = Field(default=None, description="Working directory captured for the session")
    repo_root: str | None = Field(default=None, description="Detected repo root for the session")
    host: str | None = Field(default=None, description="Origin host for the session")
    tmux_session_name: str | None = Field(default=None, description="tmux session name when applicable")
    tmux_pane_id: str | None = Field(default=None, description="tmux pane id when applicable")
    workstream_status: str | None = Field(default=None, description="Lane lifecycle status")
    summary_oneliner: str | None = Field(default=None, description="One-line session summary")
    child_session_count: int | None = Field(
        default=None,
        description="Count of persisted child sessions linked by parent_session_id",
    )
    active_child_session_count: int | None = Field(
        default=None,
        description="Count of child sessions currently considered active from persisted status/live activity",
    )
    batch_task_ids: list[str] = Field(default_factory=list, description="Task ids linked to a batch orchestrator session")
    declared_scope_paths: list[str] = Field(default_factory=list)
    observed_read_paths: list[str] = Field(default_factory=list)
    observed_write_paths: list[str] = Field(default_factory=list)
    scope_confidence: str | None = Field(default=None, description="declared | observed_write | observed_read | unknown")
    live_activity: LiveActivityResponse | None = Field(
        default=None, description="Current live execution state"
    )
    message_count: int
    event_count: int | None = Field(
        default=None,
        description="Count of persisted session events",
    )
    total_input_tokens: int = Field(default=0, description="Total input tokens")
    total_output_tokens: int = Field(default=0, description="Total output tokens")
    created_at: datetime
    updated_at: datetime
    status_source: str = Field(
        default="session",
        description="Authority for row status beacon: session or runtime",
    )
    status_matches_live: bool = Field(
        default=True,
        description="Whether persisted session status matches current runtime status",
    )


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


class CreateSessionEventRequest(BaseModel):
    """Request body for creating a lightweight session event.

    Used by CC PostToolUse hook to record tool executions.
    """

    event_type: str = Field(
        default="tool_use",
        description="Event type: tool_use, tool_result, error",
    )
    tool_name: str | None = Field(default=None, description="Tool name (Write, Edit, Bash, etc.)")
    tool_input: dict[str, object] | None = Field(
        default=None, description="Tool input (file paths, command, etc.)"
    )
    content: str | None = Field(default=None, description="Text content")
    tool_output: dict[str, object] | None = Field(
        default=None, description="Tool output summary"
    )
    model_used: str | None = Field(default=None, description="Model used for this event")
    agent_id: str | None = Field(default=None, description="Agent identifier")


class CreateSessionEventResponse(BaseModel):
    """Response body for creating a session event."""

    event_id: str = Field(..., description="Created event UUID")
    session_id: str = Field(..., description="Session ID")
    sequence: int = Field(..., description="Event sequence number")
