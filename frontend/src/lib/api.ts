/**
 * API client for Agent Hub backend.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8003";

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
