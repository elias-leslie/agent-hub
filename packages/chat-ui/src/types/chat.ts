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
  /** How much of the answer text had streamed when the call started; the transcript layout puts the call there. Absent for a turn stored before the server recorded it. */
  contentOffset?: number;
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

/** One compaction of the history: the older messages were summarized before a model call. */
export interface ChatCompaction {
  /** `ok`, or `failed` (the turn then ends with an error). */
  status: string;
  /** Estimated prompt size before and after; absent when the server did not say. */
  tokensBefore?: number;
  tokensAfter?: number;
  messagesSummarized?: number;
  summarizerModel?: string;
  costUsd?: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: Date;
  /** `compaction`: a system line where the history was summarized (`compaction` has the sizes). Not part of the conversation sent to the model. */
  kind?: "compaction";
  compaction?: ChatCompaction;
  /**
   * A stand-in answer the server wrote for a turn that has tool activity but no stored answer. Its `content` is the
   * server's note, not the model's: while the turn still runs it is not shown.
   */
  incomplete?: boolean;
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
  /** The model asked for, the one that answered, and whether a fallback served the turn. */
  requestedModel?: string;
  servedModel?: string;
  fallbackUsed?: boolean;
  fallbackReason?: string;
  /** Interrupted model turns the backend re-ran for this answer; the discarded partial output is not kept. */
  retries?: Array<{ attempt?: number; max?: number; reason?: string }>;
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
  /** How long the model spent thinking, in ms: measured live, or as the server stored it. Absent when not recorded. */
  thinkingMs?: number;
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
  | "cancel_acknowledged"
  | "error"
  | "tool_use"
  | "tool_start"
  | "tool_result"
  | "turn_retry"
  | "context_compacted";
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
  model_used?: string;
  fallback_used?: boolean;
  fallback_reason?: string;
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
  // Interrupted model turn being re-run (on 'turn_retry'); its partial output is void
  attempt?: number;
  max_retries?: number;
  reason?: string;
  // History summarized before a model call (on 'context_compacted'); `status` is "ok" or "failed"
  status?: string;
  tokens_before?: number;
  tokens_after?: number;
  messages_summarized?: number;
  summarizer_model?: string | null;
  // Tool use fields (on 'tool_use')
  tool_name?: string;
  tool_input?: Record<string, unknown>;
  tool_id?: string;
  // Tool result fields (on 'tool_result')
  tool_result?: string;
  tool_status?: "running" | "complete" | "error";
  // Cost of the turn (on 'done')
  cost_usd?: number | null;
}

export type StreamStatus =
  | "idle"
  | "connecting"
  | "streaming"
  | "reconnecting"
  | "cancelling"
  | "error";
