/**
 * Type definitions for chat streaming.
 */

import type { ChatMessage, ToolExecution } from "@/types/chat";

/**
 * Internal state for tracking a stream's accumulated content.
 */
export interface StreamState {
  content: string;
  thinking: string;
  tools: ToolExecution[];
}

/**
 * Session data returned from the backend.
 */
export interface SessionData {
  id: string;
  messages?: Array<{
    id: number;
    role: string;
    content: string;
    created_at: string;
    agent_name?: string;
    model_used?: string;
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
  project_id: string;
  stream: boolean;
  use_memory: boolean;
  memory_group_id: string;
  tier_preference?: string;
}
