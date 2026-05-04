/**
 * Session event types for full observability timeline.
 * Matches backend SessionEventType class.
 */

export type SessionEventType =
  | 'user_message'
  | 'assistant_message'
  | 'system_message'
  | 'thinking'
  | 'tool_use'
  | 'tool_result'
  | 'memory_inject'
  | 'memory_cite'
  | 'error'
  | 'child_session_started'
  | 'child_session_update'
  | 'child_session_blocked'
  | 'child_session_result'

/**
 * Full event data from GET /api/sessions/{id}/events endpoint.
 */
export interface TimelineEvent {
  id: string
  turn: number
  sequence: number
  event_type: SessionEventType
  role: string | null
  content: string | null
  tool_name: string | null
  tool_input: Record<string, unknown> | null
  tool_output: Record<string, unknown> | null
  tokens: number | null
  duration_ms: number | null
  model_used: string | null
  agent_id: string | null
  agent_name: string | null
  transport?: string | null
  surface?: string | null
  chat_id?: string | null
  message_id?: string | null
  pane_id?: string | null
  source_client?: string | null
  created_at: string
}

/**
 * Response from GET /api/sessions/{id}/events
 */
export interface SessionEventsResponse {
  session_id: string
  events: TimelineEvent[]
  total: number
  max_turn: number
}

/**
 * Legacy WebSocket event types (for real-time streaming)
 */
export type LegacySessionEventType =
  | 'session_start'
  | 'message'
  | 'tool_use'
  | 'tool_result'
  | 'complete'
  | 'error'

/**
 * Session event received from WebSocket.
 */
export interface SessionEvent {
  event_type: LegacySessionEventType
  session_id: string
  timestamp: string
  data: SessionEventData
}

/**
 * Event-specific data payloads.
 */
export type SessionEventData =
  | SessionStartData
  | MessageData
  | ToolUseData
  | ToolResultData
  | CompleteData
  | ErrorData

export interface SessionStartData {
  model: string
  project_id?: string
}

export interface MessageData {
  role: 'user' | 'assistant' | 'system'
  content: string
  tokens?: number
}

export interface ToolUseData {
  tool_name: string
  tool_input: Record<string, unknown>
  tool_output?: unknown
}

export interface ToolResultData {
  tool_name?: string | null
  tool_output?: unknown
  duration_ms?: number | null
  is_error?: boolean | null
}

export interface CompleteData {
  input_tokens: number
  output_tokens: number
  cost?: number
}

export interface ErrorData {
  error_type: string
  error_message: string
}

/**
 * Subscribe request sent to WebSocket.
 */
export interface SubscribeRequest {
  type: 'subscribe' | 'unsubscribe' | 'update'
  session_ids?: string[]
  event_types?: LegacySessionEventType[]
}

/**
 * Response to subscription actions.
 */
export interface SubscribeResponse {
  type: 'subscribed' | 'updated' | 'unsubscribed' | 'error'
  subscription_id?: string
  message?: string
}

/**
 * Connection status for WebSocket.
 */
export type ConnectionStatus =
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'error'
