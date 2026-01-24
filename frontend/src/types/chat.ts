/**
 * Chat types for Agent Hub frontend.
 */

/**
 * Tool execution state for tracking tool calls and results.
 */
export interface ToolExecution {
  id: string;
  name: string;
  input: Record<string, unknown>;
  status: "running" | "complete" | "error";
  result?: string;
  startedAt: Date;
  completedAt?: Date;
}

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
  // Provider/model identification
  agentId?: string;
  agentName?: string;
  agentProvider?: "claude" | "gemini";
  /** Model identifier (e.g., "claude-sonnet-4-5", "gemini-3-flash-preview") */
  agentModel?: string;
  isDeliberation?: boolean;
  isConsensus?: boolean;
  replyToAgentId?: string;
  // Extended thinking
  thinking?: string;
  thinkingTokens?: number;
  // Output usage / truncation
  truncated?: boolean;
  maxTokensRequested?: number;
  modelLimit?: number;
  truncationWarning?: string;
  // Tool execution
  toolExecutions?: ToolExecution[];
}

export interface StreamRequest {
  type: "request" | "cancel";
  model?: string;
  messages?: Array<{ role: string; content: string }>;
  temperature?: number;
  session_id?: string;
  // Tool-enabled mode
  working_dir?: string;
  tools_enabled?: boolean;
}

export interface StreamMessage {
  type:
    | "connected"
    | "content"
    | "thinking"
    | "done"
    | "cancelled"
    | "error"
    | "tool_use"
    | "tool_result";
  content?: string;
  // Session tracking (on 'connected'/'done'/'cancelled')
  session_id?: string;
  // Provider info (on 'connected'/'done'/'cancelled')
  provider?: "claude" | "gemini";
  model?: string;
  input_tokens?: number;
  output_tokens?: number;
  thinking_tokens?: number;
  finish_reason?: string;
  error?: string;
  // Output usage fields (on 'done')
  max_tokens_requested?: number;
  model_limit?: number;
  was_truncated?: boolean;
  truncation_warning?: string;
  // Structured output fields (on 'done' when JSON mode)
  parsed_json?: Record<string, unknown>;
  // Tool use fields (on 'tool_use')
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  tool_id?: string;
  // Tool result fields (on 'tool_result')
  tool_result?: string;
  tool_status?: "running" | "complete" | "error";
}

export type StreamStatus =
  | "idle"
  | "connecting"
  | "streaming"
  | "cancelling"
  | "error";
