/**
 * Session event types for real-time monitoring.
 */

export type SessionEventType =
  | "session_start"
  | "message"
  | "tool_use"
  | "complete"
  | "error";

/**
 * Session event received from WebSocket.
 */
export interface SessionEvent {
  event_type: SessionEventType;
  session_id: string;
  timestamp: string;
  data: SessionEventData;
}

/**
 * Event-specific data payloads.
 */
export type SessionEventData =
  | SessionStartData
  | MessageData
  | ToolUseData
  | CompleteData
  | ErrorData;

export interface SessionStartData {
  model: string;
  project_id?: string;
}

export interface MessageData {
  role: "user" | "assistant" | "system";
  content: string;
  tokens?: number;
}

export interface ToolUseData {
  tool_name: string;
  tool_input: Record<string, unknown>;
  tool_output?: unknown;
}

export interface CompleteData {
  input_tokens: number;
  output_tokens: number;
  cost?: number;
}

export interface ErrorData {
  error_type: string;
  error_message: string;
}

/**
 * Subscribe request sent to WebSocket.
 */
export interface SubscribeRequest {
  type: "subscribe" | "unsubscribe" | "update";
  session_ids?: string[];
  event_types?: SessionEventType[];
}

/**
 * Response to subscription actions.
 */
export interface SubscribeResponse {
  type: "subscribed" | "updated" | "unsubscribed" | "error";
  subscription_id?: string;
  message?: string;
}

/**
 * Connection status for WebSocket.
 */
export type ConnectionStatus =
  | "disconnected"
  | "connecting"
  | "connected"
  | "error";
