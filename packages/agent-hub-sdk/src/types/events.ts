/**
 * Live session events from the owner-only WebSocket `/api/events` (`backend/app/api/events.py`,
 * `services/events_models.py`). Written by hand.
 */

export type LiveEventType = 'session_start' | 'message' | 'tool_use' | 'tool_result' | 'complete' | 'error';

export interface SessionStartData {
    model: string;
    project_id?: string | null;
}

export interface MessageData {
    role: 'user' | 'assistant' | 'system';
    content: string;
    tokens?: number | null;
}

export interface ToolUseData {
    tool_name: string;
    tool_input: Record<string, unknown>;
    tool_output?: unknown;
}

export interface ToolResultData {
    tool_name?: string | null;
    tool_output?: unknown;
    duration_ms?: number | null;
    is_error?: boolean | null;
}

export interface CompleteData {
    input_tokens: number;
    output_tokens: number;
    cost?: number | null;
}

export interface ErrorData {
    error_type: string;
    error_message: string;
}

interface EventBase<T extends LiveEventType, D> {
    event_type: T;
    session_id: string;
    /** ISO 8601, UTC. */
    timestamp: string;
    data: D;
}

export type LiveEvent =
    | EventBase<'session_start', SessionStartData>
    | EventBase<'message', MessageData>
    | EventBase<'tool_use', ToolUseData>
    | EventBase<'tool_result', ToolResultData>
    | EventBase<'complete', CompleteData>
    | EventBase<'error', ErrorData>;

export interface EventFilters {
    /** Only these sessions; empty or unset means all. */
    sessionIds?: string[];
    /** Only these event types; empty or unset means all. */
    eventTypes?: LiveEventType[];
}

export type ConnectionStatus = 'connecting' | 'connected' | 'reconnecting' | 'closed';

/** The part of the platform `WebSocket` the SDK uses; `ws` and undici sockets fit it too. */
export interface WebSocketLike {
    send(data: string): void;
    close(code?: number, reason?: string): void;
    onopen: ((event: unknown) => void) | null;
    onmessage: ((event: { data: unknown }) => void) | null;
    onerror: ((event: unknown) => void) | null;
    onclose: ((event: { code?: number; reason?: string }) => void) | null;
}

/**
 * Open a socket to `url`. `headers` are the client's headers (the owner token, for one): browsers cannot send headers
 * on a WebSocket, so a browser factory ignores them and relies on cookies or same-origin access.
 */
export type WebSocketFactory = (url: string, init: { headers: Record<string, string> }) => WebSocketLike;
