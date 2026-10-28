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
  /** Where the current model turn began; a turn_retry drops everything after it */
  turnStart?: { content: number; thinking: number; tools: number };
}

/**
 * A tool call as the session stores it.
 */
export interface SessionToolExecution {
  id: string;
  name: string;
  input?: Record<string, unknown> | null;
  status: string;
  result?: string | null;
  duration_ms?: number | null;
}

/**
 * Message history entry for API requests.
 */
export interface MessageHistoryEntry {
  role: string;
  content: string;
}

export type PromptMode = "full" | "chat" | "none";

/**
 * Completion request body for the API.
 */
export interface CompletionRequest {
  agent_slug?: string | null;
  /** Catalog model override for the agent; omitted for its own routing. */
  model?: string;
  include_roles?: string[];
  prompt_mode?: PromptMode;
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
    preferred_agent_slug?: string;
    explore_policy?: string;
    research_policy?: string;
    verifier_enabled?: boolean;
    project_id?: string;
    project_name?: string;
    task_id?: string;
    task_title?: string;
    task_summary?: string;
    design_id?: string;
    artifact_summary?: string;
    surface?: string;
    pane_id?: string;
  };
  thinking_level?: string;
  current_branch?: string;
  use_memory: boolean;
  memory_group_id: string;
}
