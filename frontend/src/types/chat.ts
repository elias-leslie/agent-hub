/**
 * Chat types for Agent Hub frontend.
 */

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: Date;
  cancelled?: boolean;
  inputTokens?: number;
  outputTokens?: number;
  edited?: boolean;
  editedAt?: Date;
  previousVersions?: string[];
}

export interface StreamRequest {
  type: "request" | "cancel";
  model?: string;
  messages?: Array<{ role: string; content: string }>;
  max_tokens?: number;
  temperature?: number;
  session_id?: string;
}

export interface StreamMessage {
  type: "content" | "done" | "cancelled" | "error";
  content?: string;
  input_tokens?: number;
  output_tokens?: number;
  finish_reason?: string;
  error?: string;
}

export type StreamStatus = "idle" | "connecting" | "streaming" | "cancelling" | "error";
