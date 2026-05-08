/**
 * Type definitions for chat streaming.
 */

import type { ChatMessage, ToolExecution } from "../../types/chat";

/**
 * Internal state for tracking a stream's accumulated content.
 */
export interface StreamState {
  content: string;
  thinking: string;
  tools: ToolExecution[];
  /** Last processed sequence number — events with seq <= this are skipped on reconnect */
  lastSeq: number;
}

/**
 * Session data returned from the backend.
 */
export interface SessionToolExecution {
  id: string;
  name: string;
  input?: Record<string, unknown> | null;
  status: string;
  result?: string | null;
  duration_ms?: number | null;
}

export interface SessionData {
  id: string;
  project_id?: string;
  provider?: string;
  routing_mode?: string | null;
  workload_profile?: string | null;
  routing_decision_id?: string | null;
  auto_candidate_model_id?: string | null;
  routing_canary_percent?: number | null;
  messages?: Array<{
    id: number;
    role: string;
    content: string;
    created_at: string;
    agent_name?: string;
    model_used?: string;
    model_display_name?: string | null;
    agent_display_name?: string | null;
    thinking?: string | null;
    thinking_tokens?: number | null;
    tool_executions?: SessionToolExecution[];
  }>;
}

/**
 * Message history entry for API requests.
 */
export interface MessageHistoryEntry {
  role: string;
  content: string;
}

/**
 * Completion request body for the API.
 */
export interface CompletionRequest {
  agent_slug: string;
  messages: MessageHistoryEntry[];
  temperature: number;
  session_id?: string;
  working_dir?: string;
  tools_enabled: boolean;
  execute_tools?: boolean;
  project_id: string;
  external_id?: string;
  parent_session_id?: string;
  source_metadata?: {
    transport?: string;
    surface?: string;
    chat_id?: string;
    message_id?: string;
    pane_id?: string;
    source_client?: string;
  };
  work_context?: {
    mode?: string;
    routing_mode?: string;
    preferred_agent_slug?: string;
    explore_policy?: string;
    research_policy?: string;
    verifier_enabled?: boolean;
    project_id?: string;
    project_name?: string;
    task_id?: string;
    task_title?: string;
    task_summary?: string;
    feedback_id?: string;
    design_id?: string;
    artifact_summary?: string;
    surface?: string;
    pane_id?: string;
  };
  thinking_level?: string;
  current_branch?: string;
  stream: boolean;
  use_memory: boolean;
  memory_group_id: string;
}
