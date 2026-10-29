/**
 * Turn streaming types, written by hand from the wire contract in `backend/app/api/complete/sse_writer.py`
 * (events) and `request_schemas.py` (`CompletionRequest`). Only the fields a client sets are listed.
 */

export interface TurnContentBlock {
    type: string;
    [key: string]: unknown;
}

export interface TurnMessage {
    role: 'user' | 'assistant' | 'system' | (string & {});
    /** Text, or typed blocks (text, image, audio). */
    content: string | TurnContentBlock[];
}

export interface TurnTool {
    name: string;
    description: string;
    input_schema: Record<string, unknown>;
    allowed_callers?: string[];
}

export interface TurnSourceMetadata {
    transport?: string | null;
    surface?: string | null;
    chat_id?: string | null;
    message_id?: string | null;
    pane_id?: string | null;
    source_client?: string | null;
}

export interface TurnWorkContext {
    mode?: string;
    preferred_agent_slug?: string | null;
    explore_policy?: string | null;
    research_policy?: string | null;
    verifier_enabled?: boolean | null;
    project_id?: string | null;
    project_name?: string | null;
    task_id?: string | null;
    task_title?: string | null;
    task_summary?: string | null;
    design_id?: string | null;
    artifact_summary?: string | null;
    surface?: string | null;
    pane_id?: string | null;
}

export type ThinkingLevel = 'minimal' | 'low' | 'medium' | 'high' | 'ultrathink';

/** Body of `POST /api/complete`. `stream` is set by the SDK; do not pass it. */
export interface TurnRequest {
    messages: TurnMessage[];
    project_id: string;
    /** Required in practice: every agentic workload is routed through an agent. */
    agent_slug?: string | null;
    /** Catalog model override for the agent. Omit for the agent's own routing. */
    model?: string | null;
    system_prompt?: string | null;
    temperature?: number;
    /** An existing session to continue. */
    session_id?: string | null;
    parent_session_id?: string | null;
    source_metadata?: TurnSourceMetadata | null;
    work_context?: TurnWorkContext | null;
    external_id?: string | null;
    enable_caching?: boolean;
    cache_ttl?: string;
    response_format?: { type: string; schema?: Record<string, unknown> | null } | null;
    thinking_level?: ThinkingLevel | null;
    auto_thinking?: boolean;
    tools?: TurnTool[] | null;
    enable_programmatic_tools?: boolean;
    container_id?: string | null;
    use_memory?: boolean;
    memory_group_id?: string | null;
    task_type?: string | null;
    phase?: string | null;
    disable_agent_fallbacks?: boolean;
    include_roles?: string[] | null;
    prompt_mode?: 'full' | 'chat' | 'none' | null;
    max_turns?: number;
    working_dir?: string | null;
    execute_tools?: boolean;
    read_only?: boolean;
    trace_id?: string | null;
    current_branch?: string | null;
}

/** Which agent and model served the turn; on `content` and `done` once the route is known. */
export interface TurnRouting {
    /** The model asked for. */
    model?: string;
    provider?: string;
    agent_used?: string;
    /** The model that answered (differs from `model` after a fallback). */
    model_used?: string;
    fallback_used?: boolean;
    fallback_reason?: string;
}

interface Seq {
    /** Monotonic per stream; the SDK drops any event whose `seq` it has already seen. */
    seq: number;
}

export interface ConnectedEvent extends Seq {
    type: 'connected';
    session_id: string;
    model?: string;
    provider?: string;
    /** The server-side turn this stream belongs to; pass it as `turnId` to `turns.attach` to be sure of the same turn. */
    turn_id?: string;
}

export interface ContentEvent extends Seq, TurnRouting {
    type: 'content';
    content: string;
}

export interface ThinkingEvent extends Seq {
    type: 'thinking';
    content: string;
}

export interface ToolUseEvent extends Seq {
    type: 'tool_use';
    tool_id: string;
    tool_name: string;
    tool_input: Record<string, unknown>;
}

export interface ToolStartEvent extends Seq {
    type: 'tool_start';
    tool_id: string;
    tool_name: string;
}

export type ToolStatus = 'running' | 'complete' | 'error';

export interface ToolResultEvent extends Seq {
    type: 'tool_result';
    tool_id: string;
    tool_result: string;
    tool_status: ToolStatus;
}

/** An interrupted model turn is being re-run: its partial output (since the last tool result) is void. */
export interface TurnRetryEvent extends Seq {
    type: 'turn_retry';
    attempt: number;
    max_retries: number;
    reason: string;
}

/**
 * Before this model call the history was summarized (the turn goes on from the shorter context). `status` is `ok`, or
 * `failed` (the turn then ends with an `error`). The record is also stored on the session as a `compaction` message.
 */
export interface ContextCompactedEvent extends Seq {
    type: 'context_compacted';
    status: 'ok' | 'failed' | (string & {});
    /** Estimated prompt size before and after the summary. */
    tokens_before: number;
    tokens_after: number;
    context_window?: number;
    threshold?: number;
    messages_summarized?: number;
    messages_kept?: number;
    summarizer_model?: string | null;
    cost_usd?: number;
    error?: string | null;
}

export interface CancelAcknowledgedEvent extends Seq {
    type: 'cancel_acknowledged';
    session_id: string;
}

export interface DoneEvent extends Seq, TurnRouting {
    type: 'done';
    session_id: string;
    cost_usd?: number | null;
    finish_reason?: string | null;
    input_tokens?: number;
    output_tokens?: number;
    cache_read_tokens?: number;
    cache_write_tokens?: number;
    thinking_tokens?: number;
    model_display_name?: string;
    was_truncated?: boolean;
    max_tokens_requested?: number;
    model_limit?: number;
    truncation_warning?: string;
    parsed_json?: Record<string, unknown>;
}

export interface TurnErrorEvent extends Seq {
    type: 'error';
    error: string;
    model?: string;
    provider?: string;
    session_id?: string;
    /** `turn_interrupted` when the backend stopped while the turn was running; the turn did not finish. */
    code?: string;
}

/**
 * Only from `turns.attach`: no turn is running and the server no longer holds the last one's events. It carries no
 * `seq`. `last_state` is how that turn ended (`completed`, `error`, `cancelled`) or `none`; read the session for
 * the stored result.
 */
export interface IdleEvent {
    type: 'idle';
    session_id: string;
    last_state: string;
    turn_id?: string | null;
    ended_at?: string | null;
    seq?: undefined;
}

export type TurnEvent =
    | ConnectedEvent
    | ContentEvent
    | ThinkingEvent
    | ToolUseEvent
    | ToolStartEvent
    | ToolResultEvent
    | TurnRetryEvent
    | ContextCompactedEvent
    | CancelAcknowledgedEvent
    | DoneEvent
    | TurnErrorEvent;

export type TurnEventType = TurnEvent['type'];

/** The events that end a turn: after one of these the stream is over. */
export type TerminalTurnEvent = DoneEvent | TurnErrorEvent | CancelAcknowledgedEvent;
