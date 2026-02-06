/**
 * Dashboard stats API
 */

import { getApiBaseUrl, fetchApi } from "../api-config";

const API_BASE = `${getApiBaseUrl()}/api`;

export interface RequestMetrics {
  total_requests: number;
  avg_latency_ms: number;
  p50_latency_ms: number;
  p95_latency_ms: number;
  success_rate: number;
  error_count: number;
}

export interface MemoryMetrics {
  total_injections: number;
  avg_latency_ms: number;
  avg_tokens: number;
  total_mandates: number;
  total_guardrails: number;
  total_references: number;
}

export interface TruncationMetrics {
  total_truncations: number;
  truncation_rate: number;
  avg_output_tokens: number;
}

export interface ModelBreakdown {
  model: string;
  avg_latency_ms: number;
  request_count: number;
}

export interface DashboardStatsResponse {
  period_days: number;
  period_start: string;
  period_end: string;
  requests: RequestMetrics;
  memory: MemoryMetrics;
  truncations: TruncationMetrics;
  by_model: ModelBreakdown[];
  active_sessions: number;
  total_sessions: number;
  total_cost_usd: number;
  total_tokens: number;
}

export async function fetchDashboardStats(days: number = 7): Promise<DashboardStatsResponse> {
  const response = await fetchApi(`${API_BASE}/dashboard/stats?days=${days}`);
  if (!response.ok) {
    throw new Error(`Dashboard stats fetch failed: ${response.status}`);
  }
  return response.json();
}
