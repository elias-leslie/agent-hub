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
  // Multi-agent fields
  agentId?: string;
  agentName?: string;
  agentProvider?: "claude" | "gemini";
  isDeliberation?: boolean;
  isConsensus?: boolean;
  replyToAgentId?: string;
  // Extended thinking
  thinking?: string;
  thinkingTokens?: number;
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
  type: "content" | "thinking" | "done" | "cancelled" | "error";
  content?: string;
  input_tokens?: number;
  output_tokens?: number;
  thinking_tokens?: number;
  finish_reason?: string;
  error?: string;
}

export type StreamStatus = "idle" | "connecting" | "streaming" | "cancelling" | "error";
