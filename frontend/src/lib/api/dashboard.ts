/**
 * Dashboard stats API
 */

import { fetchApi, getApiBaseUrl } from '../api-config'

const API_BASE = `${getApiBaseUrl()}/api`

/** Model-call metrics: `POST /api/complete` rows only (buffered and streaming). */
export interface RequestMetrics {
  total_requests: number
  avg_latency_ms: number | null
  p50_latency_ms: number | null
  p95_latency_ms: number | null
  /** 0-100; null when the period had no model calls. */
  success_rate: number | null
  error_count: number
}

/** Model calls for one UTC day; same population as RequestMetrics. */
export interface DailyRequestCount {
  date: string
  requests: number
  errors: number
}

export interface MemoryMetrics {
  total_injections: number
  avg_latency_ms: number
  avg_tokens: number
  total_mandates: number
  total_guardrails: number
  /** Explicitly selected references. */
  total_references: number
  /** Passive reference-index entries; kept separate from selected references. */
  total_reference_index_entries: number
  total_reference_citations: number
}

export interface ModelBreakdown {
  model: string
  avg_latency_ms: number
  request_count: number
}

export interface DashboardStatsResponse {
  period_days: number
  period_start: string
  period_end: string
  requests: RequestMetrics
  requests_by_day: DailyRequestCount[]
  memory: MemoryMetrics
  by_model: ModelBreakdown[]
  active_sessions: number
  total_sessions: number
  /** Metered spend: API-billed calls recorded in cost_logs. */
  total_cost_usd: number
  total_tokens: number
}

export async function fetchDashboardStats(
  days: number = 7,
): Promise<DashboardStatsResponse> {
  const response = await fetchApi(`${API_BASE}/dashboard/stats?days=${days}`)
  if (!response.ok) {
    throw new Error(`Dashboard stats fetch failed: ${response.status}`)
  }
  return response.json()
}

export interface ProviderHealth {
  provider: string
  state: string
  latency_ms: number | null
  /** Share of recent calls without a provider failure, 0-1. */
  availability: number | null
  consecutive_failures: number
  /** Completion calls in the last 24 hours. */
  recent_calls: number
  /** Provider failures (HTTP 5xx or 429) in the last 24 hours. */
  recent_failures: number
  last_error: string | null
}

export interface ProviderHealthResponse {
  providers: ProviderHealth[]
}

export async function fetchProviderHealth(): Promise<ProviderHealthResponse> {
  const response = await fetchApi(`${API_BASE}/dashboard/provider-health`)
  if (!response.ok) {
    throw new Error(`Provider health fetch failed: ${response.status}`)
  }
  return response.json()
}

export interface ModelLatencyStats {
  model: string
  sample_count: number
  p50_ms: number
  p95_ms: number
  p99_ms: number
}

export interface LatencyStatsResponse {
  stats: ModelLatencyStats[]
}

export async function fetchModelLatencyStats(
  days: number = 7,
): Promise<LatencyStatsResponse> {
  const response = await fetchApi(
    `${API_BASE}/models/latency-stats?days=${days}`,
  )
  if (!response.ok) {
    throw new Error(`Latency stats fetch failed: ${response.status}`)
  }
  return response.json()
}
