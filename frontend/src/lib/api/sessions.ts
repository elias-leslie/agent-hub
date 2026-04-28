/**
 * Sessions and session events API
 */

import { getApiBaseUrl, fetchApi } from "../api-config";
import type { TimelineEvent, SessionEventsResponse } from "@/types/events";

export type SessionTimelineEvent = TimelineEvent;
export type { SessionEventsResponse };

const API_BASE = `${getApiBaseUrl()}/api`;
const SESSION_EVENTS_MAX_PAGE_SIZE = 500;

export interface SessionMessage {
  id: number;
  role: string;
  content: string;
  tokens: number | null;
  agent_id: string | null;
  agent_name: string | null;
  created_at: string;
}

export interface AgentTokenBreakdown {
  agent_id: string;
  agent_name: string | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  message_count: number;
}

export interface ContextUsage {
  used_tokens: number;
  limit_tokens: number;
  percent_used: number;
  remaining_tokens: number;
  warning: string | null;
}

export interface LiveActivity {
  phase: string;
  status: string;
  summary?: string | null;
  health: string;
  stalled: boolean;
  stall_reason?: string | null;
  quiet_for_seconds?: number | null;
  last_event_type?: string | null;
  last_event_at?: string | null;
  last_model_activity_at?: string | null;
  current_tool_name?: string | null;
  current_topic?: string | null;
  last_tool_name?: string | null;
  last_topic?: string | null;
  last_tool_started_at?: string | null;
  last_tool_finished_at?: string | null;
  last_tool_error?: boolean | null;
  last_read_path?: string | null;
  last_write_path?: string | null;
  last_command?: string | null;
  last_validation_command?: string | null;
  last_command_exit_code?: number | null;
  outstanding_tool_calls: number;
  tool_calls_count: number;
  termination_reason?: string | null;
  files_touched: string[];
  last_heartbeat_at?: string | null;
  lifecycle_state?: string;
  lifecycle_reason_codes?: string[];
  dead_signals?: string[];
  anti_reap_signals?: string[];
  has_owner_lane?: boolean;
  has_specialist_lane?: boolean;
  reapable?: boolean;
  reapable_reason?: string | null;
}

export interface Session {
  id: string;
  project_id: string;
  provider: string;
  model: string;
  requested_provider?: string | null;
  requested_model?: string | null;
  effective_provider?: string | null;
  effective_model?: string | null;
  requested_model_display_name?: string | null;
  effective_model_display_name?: string | null;
  fallback_used?: boolean;
  fallback_reason?: string | null;
  status: string;
  agent_slug: string | null;
  session_type: string;
  parent_session_id?: string | null;
  external_id?: string | null;
  client_id?: string | null;
  request_source?: string | null;
  source_client?: string | null;
  source_path?: string | null;
  attribution_kind?: string | null;
  attribution_label?: string | null;
  attribution_detail?: string | null;
  current_branch?: string | null;
  working_dir?: string | null;
  repo_root?: string | null;
  host?: string | null;
  tmux_session_name?: string | null;
  tmux_pane_id?: string | null;
  workstream_status?: string | null;
  summary_oneliner?: string | null;
  child_session_count?: number | null;
  active_child_session_count?: number | null;
  batch_task_ids?: string[];
  declared_scope_paths?: string[];
  observed_read_paths?: string[];
  observed_write_paths?: string[];
  scope_confidence?: string | null;
  created_at: string;
  updated_at: string;
  live_activity?: LiveActivity | null;
  messages?: SessionMessage[];
  context_usage?: ContextUsage | null;
  agent_token_breakdown?: AgentTokenBreakdown[];
  message_count?: number | null;
  event_count?: number | null;
  total_input_tokens?: number;
  total_output_tokens?: number;
}

export interface SessionListItem {
  id: string;
  project_id: string;
  provider: string;
  model: string;
  requested_provider?: string | null;
  requested_model?: string | null;
  effective_provider?: string | null;
  effective_model?: string | null;
  requested_model_display_name?: string | null;
  effective_model_display_name?: string | null;
  fallback_used?: boolean;
  fallback_reason?: string | null;
  status: string;
  agent_slug: string | null;
  session_type: string;
  parent_session_id?: string | null;
  external_id?: string | null;
  client_id?: string | null;
  request_source?: string | null;
  source_client?: string | null;
  source_path?: string | null;
  attribution_kind?: string | null;
  attribution_label?: string | null;
  attribution_detail?: string | null;
  current_branch?: string | null;
  summary_oneliner?: string | null;
  live_activity?: LiveActivity | null;
  message_count: number;
  event_count?: number | null;
  total_input_tokens: number;
  total_output_tokens: number;
  created_at: string;
  updated_at: string;
}

export interface SessionListResponse {
  sessions: SessionListItem[];
  total: number;
  page: number;
  page_size: number;
}

export async function fetchSessions(params?: {
  project_id?: string;
  status?: string;
  agent_slug?: string;
  session_type?: string;
  page?: number;
  page_size?: number;
}): Promise<SessionListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.project_id) searchParams.set("project_id", params.project_id);
  if (params?.status) searchParams.set("status", params.status);
  if (params?.agent_slug) searchParams.set("agent_slug", params.agent_slug);
  if (params?.session_type)
    searchParams.set("session_type", params.session_type);
  if (params?.page) searchParams.set("page", params.page.toString());
  if (params?.page_size)
    searchParams.set("page_size", params.page_size.toString());

  const url = searchParams.toString()
    ? `${API_BASE}/sessions?${searchParams}`
    : `${API_BASE}/sessions`;

  const response = await fetchApi(url);
  if (!response.ok) {
    throw new Error(`Sessions fetch failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchSession(id: string): Promise<Session> {
  const response = await fetchApi(`${API_BASE}/sessions/${id}`);
  if (!response.ok) {
    throw new Error(`Session fetch failed: ${response.status}`);
  }
  return response.json();
}

export async function cancelSessionStream(sessionId: string): Promise<{ cancelled: boolean; session_id: string }> {
  const response = await fetchApi(`${API_BASE}/complete/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!response.ok) {
    throw new Error(`Session stream cancel failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchSessionEvents(
  sessionId: string,
  params?: {
    event_type?: string;
    turn?: number;
    page?: number;
    page_size?: number;
  },
): Promise<SessionEventsResponse> {
  const searchParams = new URLSearchParams();
  if (params?.event_type) searchParams.set("event_type", params.event_type);
  if (params?.turn !== undefined) searchParams.set("turn", params.turn.toString());
  if (params?.page) searchParams.set("page", params.page.toString());
  if (params?.page_size) searchParams.set("page_size", params.page_size.toString());

  const url = searchParams.toString()
    ? `${API_BASE}/sessions/${sessionId}/events?${searchParams}`
    : `${API_BASE}/sessions/${sessionId}/events`;

  const response = await fetchApi(url);
  if (!response.ok) {
    throw new Error(`Session events fetch failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchAllSessionEvents(
  sessionId: string,
  params?: {
    event_type?: string;
    turn?: number;
    page_size?: number;
    max_pages?: number;
  },
): Promise<SessionEventsResponse> {
  const pageSize = Math.min(
    params?.page_size ?? SESSION_EVENTS_MAX_PAGE_SIZE,
    SESSION_EVENTS_MAX_PAGE_SIZE,
  );
  const maxPages = params?.max_pages ?? 100;
  const firstPage = await fetchSessionEvents(sessionId, {
    event_type: params?.event_type,
    turn: params?.turn,
    page: 1,
    page_size: pageSize,
  });

  if (firstPage.events.length >= firstPage.total || firstPage.events.length === 0) {
    return firstPage;
  }

  const allEvents = [...firstPage.events];
  let maxTurn = firstPage.max_turn;

  for (let page = 2; page <= maxPages && allEvents.length < firstPage.total; page += 1) {
    const nextPage = await fetchSessionEvents(sessionId, {
      event_type: params?.event_type,
      turn: params?.turn,
      page,
      page_size: pageSize,
    });
    if (nextPage.events.length === 0) {
      break;
    }
    allEvents.push(...nextPage.events);
    maxTurn = Math.max(maxTurn, nextPage.max_turn);
  }

  return {
    session_id: firstPage.session_id,
    events: allEvents,
    total: firstPage.total,
    max_turn: maxTurn,
  };
}
