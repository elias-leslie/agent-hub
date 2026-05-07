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

export interface ChatArtifact {
  id: string;
  type: "code_diff" | "file_patch" | "generated_file" | "command_output" | "screenshot" | "dom_extract" | "browser_replay" | "annotation_set" | "report" | "other";
  title: string;
  summary?: string;
  mimeType?: string;
  visibility?: "app" | "model" | "private";
}

export interface ChatAttachment {
  id: string;
  name: string;
  type?: string;
  sizeBytes?: number;
}

export interface ChatPermissionRequest {
  id: string;
  action: string;
  tool?: string;
  target?: string;
  risk?: string;
  status: "requested" | "granted" | "denied";
}

export interface ChatContextHint {
  label: string;
  value: string;
  tone?: "default" | "warning" | "danger";
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: Date;
  cancelled?: boolean;
  inputTokens?: number;
  outputTokens?: number;
  latency?: number;
  edited?: boolean;
  editedAt?: Date;
  previousVersions?: string[];
  // Provider/model identification
  agentId?: string;
  agentName?: string;
  agentProvider?: "claude" | "gemini" | "openrouter" | "openai" | "xai" | "zhipu";
  /** Agent slug or effective model identifier used for display. */
  agentModel?: string;
  routingMode?: string;
  workloadProfile?: string;
  routingDecisionId?: string;
  autoCandidateModel?: string;
  routingCanaryPercent?: number;
  /** Target agent slug specified via @mention (for user messages) */
  targetModel?: string;
  /** Group ID for parallel responses to the same user message */
  responseGroupId?: string;
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
  compacted?: boolean;
  contextHints?: ChatContextHint[];
  costUsd?: number;
  statusLabel?: string;
  artifacts?: ChatArtifact[];
  attachments?: ChatAttachment[];
  permissionRequests?: ChatPermissionRequest[];
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
  | "tool_start"
  | "tool_result";
  /** Monotonic sequence number for ordering and dedup on reconnect */
  seq?: number;
  content?: string;
  // Session tracking (on 'connected'/'done'/'cancelled')
  session_id?: string;
  // Provider info (on 'connected'/'done'/'cancelled')
  provider?: string;
  model?: string;
  model_display_name?: string;
  agent_used?: string;
  input_tokens?: number;
  output_tokens?: number;
  thinking_tokens?: number;
  finish_reason?: string;
  routing_mode?: string;
  workload_profile?: string;
  routing_decision_id?: string;
  auto_candidate_model_id?: string;
  routing_canary_percent?: number;
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
  | "reconnecting"
  | "cancelling"
  | "error";
