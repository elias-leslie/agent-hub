/**
 * Sessions, written by hand from `SessionCreate` / `SessionResponse` / `SessionListResponse` /
 * `SessionEventsResponse` in the backend OpenAPI. Optional response fields the SDK does not model are left out.
 */

export interface SessionCreateRequest {
    project_id: string;
    provider: string;
    model: string;
    /** Custom id; creating with an existing id returns that session. */
    session_id?: string | null;
    session_type?: string;
    agent_slug?: string | null;
    external_id?: string | null;
    current_branch?: string | null;
    cwd?: string | null;
    declared_scope_paths?: string[];
    observed_read_paths?: string[];
    observed_write_paths?: string[];
    scope_confidence?: string | null;
    provider_metadata?: Record<string, unknown>;
    work_role?: Record<string, unknown> | null;
}

export interface SessionToolExecution {
    id: string;
    name: string;
    input?: Record<string, unknown> | null;
    status?: string | null;
    result?: string | null;
    /** How much of the message text (UTF-16 units) had streamed when the call started; absent for turns stored before this was recorded. */
    content_offset?: number | null;
    [key: string]: unknown;
}

export interface SessionMessage {
    id: string;
    role: string | null;
    content: string | null;
    tokens: number | null;
    created_at: string;
    agent_id?: string | null;
    agent_name?: string | null;
    model_used?: string | null;
    model_display_name?: string | null;
    agent_display_name?: string | null;
    thinking?: string | null;
    thinking_tokens?: number | null;
    /** How long the model thought, in ms; absent when not recorded. */
    thinking_ms?: number | null;
    tool_executions?: SessionToolExecution[];
}

export interface SessionSummary {
    id: string;
    project_id: string;
    provider: string;
    model: string;
    status: string;
    /** `running` while a chat turn is in flight for the session on the server, else `idle`. */
    turn_state?: 'running' | 'idle';
    /** Where the running turn is: `waiting_for_model`, `thinking`, `responding`, `running_tool[:name]` or `retrying`. */
    turn_phase?: string | null;
    agent_slug?: string | null;
    session_type?: string;
    parent_session_id?: string | null;
    external_id?: string | null;
    requested_model?: string | null;
    effective_model?: string | null;
    fallback_used?: boolean;
    title?: string | null;
    summary_oneliner?: string | null;
    message_count?: number | null;
    event_count?: number | null;
    total_input_tokens?: number;
    total_output_tokens?: number;
    /** Cost of the session's logged model calls in USD; null when none were logged. */
    total_cost_usd?: number | null;
    last_active_at?: string | null;
    created_at: string;
    updated_at: string;
    [key: string]: unknown;
}

/** `GET /api/sessions/{id}`: the summary plus `messages` unless fetched without them. */
export interface Session extends SessionSummary {
    messages?: SessionMessage[];
}

export interface ListSessionsParams {
    project_id?: string;
    status?: string;
    agent_slug?: string;
    parent_session_id?: string;
    session_type?: string;
    external_id?: string;
    q?: string;
    /** Comma list: coding, chat, completion, image. */
    kind?: string;
    since?: string;
    model?: string;
    roots_only?: boolean;
    sort_by?: string;
    sort_direction?: 'asc' | 'desc';
    page?: number;
    page_size?: number;
    /** `next_cursor` from the previous page; when given, `page` is ignored. */
    cursor?: string;
}

export interface SessionList {
    sessions: SessionSummary[];
    total: number;
    page: number;
    page_size: number;
    next_cursor?: string | null;
}

export interface CloseSessionResult {
    id: string;
    status: string;
    message: string;
}

export interface ForkSessionRequest {
    /** The turn to fork at; omitted forks at the current state. */
    fork_at_turn?: number | null;
}

export interface ForkSessionResult {
    /** The new session. */
    id: string;
    parent_session_id: string;
    fork_point_turn: number;
    message_count: number;
    branch_status: string;
}

export interface SessionEventsParams {
    event_type?: string;
    turn?: number;
    page?: number;
    page_size?: number;
    snapshot?: string;
    /** Comma list of event types to leave out. */
    exclude_types?: string;
    q?: string;
    /** `next_after` from the previous window; replaces `page`. */
    after?: string;
    order?: 'asc' | 'desc';
}

export interface SessionTimelineEvent {
    id: string;
    turn: number;
    sequence: number;
    event_type: string;
    created_at: string;
    role?: string | null;
    content?: string | null;
    tool_name?: string | null;
    call_id?: string | null;
    tool_input?: Record<string, unknown> | null;
    tool_output?: Record<string, unknown> | null;
    tokens?: number | null;
    duration_ms?: number | null;
    model_used?: string | null;
    agent_id?: string | null;
    agent_name?: string | null;
    usage?: Record<string, unknown> | null;
    [key: string]: unknown;
}

export interface SessionEventsPage {
    session_id: string;
    events?: SessionTimelineEvent[];
    total: number;
    max_turn: number;
    snapshot: string;
    next_after?: string | null;
}
