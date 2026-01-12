/**
 * API client for Agent Hub backend.
 * Uses /api/* paths which Next.js rewrites to the backend.
 */

const API_BASE = "/api";

export interface ProviderHealthDetails {
  state: "healthy" | "degraded" | "unavailable" | "unknown";
  latency_ms: number;
  error_rate: number;
  availability: number;
  consecutive_failures: number;
  last_check: number | null;
  last_success: number | null;
  last_error: string | null;
}

export interface ProviderStatus {
  name: string;
  available: boolean;
  configured: boolean;
  error: string | null;
  health: ProviderHealthDetails | null;
}

export interface StatusResponse {
  status: "healthy" | "degraded";
  service: string;
  database: string;
  providers: ProviderStatus[];
  uptime_seconds: number;
}

export interface CostAggregation {
  group_key: string;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  total_cost_usd: number;
  request_count: number;
}

export interface CostAggregationResponse {
  aggregations: CostAggregation[];
  total_cost_usd: number;
  total_tokens: number;
  total_requests: number;
}

export async function fetchStatus(): Promise<StatusResponse> {
  const response = await fetch(`${API_BASE}/status`);
  if (!response.ok) {
    throw new Error(`Status fetch failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchCosts(params: {
  group_by?: "project" | "model" | "day" | "week" | "month" | "none";
  days?: number;
  project_id?: string;
  model?: string;
}): Promise<CostAggregationResponse> {
  const searchParams = new URLSearchParams();
  if (params.group_by) searchParams.set("group_by", params.group_by);
  if (params.days) searchParams.set("days", params.days.toString());
  if (params.project_id) searchParams.set("project_id", params.project_id);
  if (params.model) searchParams.set("model", params.model);

  const response = await fetch(`${API_BASE}/analytics/costs?${searchParams}`);
  if (!response.ok) {
    throw new Error(`Costs fetch failed: ${response.status}`);
  }
  return response.json();
}

// Credentials API
export interface Credential {
  id: number;
  provider: string;
  credential_type: string;
  value_masked: string;
  created_at: string;
  updated_at: string;
}

export interface CredentialListResponse {
  credentials: Credential[];
  total: number;
}

export interface CredentialCreate {
  provider: string;
  credential_type: string;
  value: string;
}

export async function fetchCredentials(
  provider?: string,
): Promise<CredentialListResponse> {
  const url = provider
    ? `${API_BASE}/credentials?provider=${provider}`
    : `${API_BASE}/credentials`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Credentials fetch failed: ${response.status}`);
  }
  return response.json();
}

export async function createCredential(
  data: CredentialCreate,
): Promise<Credential> {
  const response = await fetch(`${API_BASE}/credentials`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Create credential failed: ${response.status}`,
    );
  }
  return response.json();
}

export async function updateCredential(
  id: number,
  value: string,
): Promise<Credential> {
  const response = await fetch(`${API_BASE}/credentials/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Update credential failed: ${response.status}`,
    );
  }
  return response.json();
}

export async function deleteCredential(id: number): Promise<void> {
  const response = await fetch(`${API_BASE}/credentials/${id}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(`Delete credential failed: ${response.status}`);
  }
}

// Sessions API
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

export interface Session {
  id: string;
  project_id: string;
  provider: string;
  model: string;
  status: string;
  purpose: string | null;
  session_type: string;
  created_at: string;
  updated_at: string;
  messages?: SessionMessage[];
  context_usage?: ContextUsage | null;
  agent_token_breakdown?: AgentTokenBreakdown[];
  total_input_tokens?: number;
  total_output_tokens?: number;
}

export interface SessionListItem {
  id: string;
  project_id: string;
  provider: string;
  model: string;
  status: string;
  purpose: string | null;
  session_type: string;
  message_count: number;
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
  purpose?: string;
  session_type?: string;
  page?: number;
  page_size?: number;
}): Promise<SessionListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.project_id) searchParams.set("project_id", params.project_id);
  if (params?.status) searchParams.set("status", params.status);
  if (params?.purpose) searchParams.set("purpose", params.purpose);
  if (params?.session_type)
    searchParams.set("session_type", params.session_type);
  if (params?.page) searchParams.set("page", params.page.toString());
  if (params?.page_size)
    searchParams.set("page_size", params.page_size.toString());

  const url = searchParams.toString()
    ? `${API_BASE}/sessions?${searchParams}`
    : `${API_BASE}/sessions`;

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Sessions fetch failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchSession(id: string): Promise<Session> {
  const response = await fetch(`${API_BASE}/sessions/${id}`);
  if (!response.ok) {
    throw new Error(`Session fetch failed: ${response.status}`);
  }
  return response.json();
}

// API Keys API
export interface APIKey {
  id: number;
  key_prefix: string;
  name: string | null;
  project_id: string;
  rate_limit_rpm: number;
  rate_limit_tpm: number;
  is_active: boolean;
  last_used_at: string | null;
  created_at: string;
  expires_at: string | null;
}

export interface APIKeyCreate {
  name?: string;
  project_id?: string;
  rate_limit_rpm?: number;
  rate_limit_tpm?: number;
  expires_in_days?: number;
}

export interface APIKeyCreateResponse extends APIKey {
  key: string; // Full key, shown only once
}

export interface APIKeyListResponse {
  keys: APIKey[];
  total: number;
}

export async function fetchAPIKeys(params?: {
  project_id?: string;
  include_revoked?: boolean;
}): Promise<APIKeyListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.project_id) searchParams.set("project_id", params.project_id);
  if (params?.include_revoked) searchParams.set("include_revoked", "true");

  const url = searchParams.toString()
    ? `${API_BASE}/api-keys?${searchParams}`
    : `${API_BASE}/api-keys`;

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`API keys fetch failed: ${response.status}`);
  }
  return response.json();
}

export async function createAPIKey(
  data: APIKeyCreate,
): Promise<APIKeyCreateResponse> {
  const response = await fetch(`${API_BASE}/api-keys`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Create API key failed: ${response.status}`,
    );
  }
  return response.json();
}

export async function updateAPIKey(
  id: number,
  data: { name?: string; rate_limit_rpm?: number; rate_limit_tpm?: number },
): Promise<APIKey> {
  const response = await fetch(`${API_BASE}/api-keys/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Update API key failed: ${response.status}`,
    );
  }
  return response.json();
}

export async function revokeAPIKey(id: number): Promise<APIKey> {
  const response = await fetch(`${API_BASE}/api-keys/${id}/revoke`, {
    method: "POST",
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Revoke API key failed: ${response.status}`,
    );
  }
  return response.json();
}

export async function deleteAPIKey(id: number): Promise<void> {
  const response = await fetch(`${API_BASE}/api-keys/${id}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(`Delete API key failed: ${response.status}`);
  }
}

// Feedback API
export interface MessageFeedback {
  id: number;
  message_id: string;
  session_id?: string;
  feedback_type: "positive" | "negative";
  category?: string;
  details?: string;
  created_at: string;
}

export interface FeedbackCreate {
  message_id: string;
  session_id?: string;
  feedback_type: "positive" | "negative";
  category?: string;
  details?: string;
}

export interface FeedbackStats {
  total_feedback: number;
  positive_count: number;
  negative_count: number;
  positive_rate: number;
  categories: Record<string, number>;
}

export async function submitFeedback(
  data: FeedbackCreate,
): Promise<MessageFeedback> {
  const response = await fetch(`${API_BASE}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Submit feedback failed: ${response.status}`,
    );
  }
  return response.json();
}

export async function fetchFeedbackStats(params?: {
  session_id?: string;
  days?: number;
}): Promise<FeedbackStats> {
  const searchParams = new URLSearchParams();
  if (params?.session_id) searchParams.set("session_id", params.session_id);
  if (params?.days) searchParams.set("days", params.days.toString());

  const url = searchParams.toString()
    ? `${API_BASE}/feedback/stats?${searchParams}`
    : `${API_BASE}/feedback/stats`;

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Feedback stats fetch failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchMessageFeedback(
  messageId: string,
): Promise<MessageFeedback | null> {
  const response = await fetch(`${API_BASE}/feedback/message/${messageId}`);
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Feedback fetch failed: ${response.status}`);
  }
  return response.json();
}

// User Preferences API
export interface UserPreferences {
  verbosity: "concise" | "normal" | "detailed";
  tone: "professional" | "friendly" | "technical";
  default_model: string;
}

export async function fetchUserPreferences(): Promise<UserPreferences> {
  const response = await fetch(`${API_BASE}/preferences`);
  if (!response.ok) {
    // Return defaults if not found
    if (response.status === 404) {
      return {
        verbosity: "normal",
        tone: "professional",
        default_model: "claude-sonnet-4-5",
      };
    }
    throw new Error(`Preferences fetch failed: ${response.status}`);
  }
  return response.json();
}

export async function updateUserPreferences(
  prefs: Partial<UserPreferences>,
): Promise<UserPreferences> {
  const response = await fetch(`${API_BASE}/preferences`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(prefs),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Update preferences failed: ${response.status}`,
    );
  }
  return response.json();
}

// Truncations Analytics API
export interface TruncationAggregation {
  group_key: string;
  truncation_count: number;
  avg_output_tokens: number;
  avg_max_tokens: number;
  capped_count: number;
}

export interface TruncationMetricsResponse {
  aggregations: TruncationAggregation[];
  total_truncations: number;
  truncation_rate: number;
  recent_events: Array<{
    id: number;
    model: string;
    endpoint: string;
    output_tokens: number;
    max_tokens_requested: number;
    model_limit: number;
    was_capped: boolean;
    created_at: string | null;
  }>;
}

export async function fetchTruncations(params?: {
  group_by?: "model" | "day" | "week" | "month" | "none";
  model?: string;
  project_id?: string;
  days?: number;
  include_recent?: boolean;
  limit_recent?: number;
}): Promise<TruncationMetricsResponse> {
  const searchParams = new URLSearchParams();
  if (params?.group_by) searchParams.set("group_by", params.group_by);
  if (params?.model) searchParams.set("model", params.model);
  if (params?.project_id) searchParams.set("project_id", params.project_id);
  if (params?.days) searchParams.set("days", params.days.toString());
  if (params?.include_recent !== undefined)
    searchParams.set("include_recent", params.include_recent.toString());
  if (params?.limit_recent)
    searchParams.set("limit_recent", params.limit_recent.toString());

  const url = searchParams.toString()
    ? `${API_BASE}/analytics/truncations?${searchParams}`
    : `${API_BASE}/analytics/truncations`;

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Truncations fetch failed: ${response.status}`);
  }
  return response.json();
}
