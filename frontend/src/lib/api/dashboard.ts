/**
 * Dashboard stats API
 */

import { fetchApi, getApiBaseUrl } from '../api-config'

const API_BASE = `${getApiBaseUrl()}/api`

export interface RequestMetrics {
  total_requests: number
  avg_latency_ms: number
  p50_latency_ms: number
  p95_latency_ms: number
  success_rate: number
  error_count: number
  timeout_count: number
  fallback_count: number
  fallback_success_rate: number
}

export interface MemoryMetrics {
  total_injections: number
  avg_latency_ms: number
  avg_tokens: number
  total_mandates: number
  total_guardrails: number
  total_references: number
}

export interface TruncationMetrics {
  total_truncations: number
  truncation_rate: number
  avg_output_tokens: number
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
  memory: MemoryMetrics
  truncations: TruncationMetrics
  by_model: ModelBreakdown[]
  active_sessions: number
  total_sessions: number
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
  latency_ms: number
  availability: number
  consecutive_failures: number
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

export interface HeartbeatStatusResponse {
  running: boolean
  last_run: string | null
  last_attempt: string | null
  last_success: string | null
  last_skip_reason: string | null
  last_error: string | null
  elapsed_seconds: number | null
  interval_minutes: number
  execution_state: string
  running_session_id: string | null
  running_owner_host?: string | null
  running_owner_pid?: number | null
  running_trigger?: string | null
  running_project_id?: string | null
  last_session_id?: string | null
  last_turns?: number | null
  last_tool_calls?: number | null
  last_format_compliant?: boolean | null
  last_summary_stored?: boolean | null
  last_had_error?: boolean | null
  runtime: HeartbeatRuntimeInfo | null
}

export interface HeartbeatRuntimeInfo {
  model: string
  provider: string
  model_display_name: string | null
  thinking_level: string | null
  supports_tools: boolean
  supports_thinking: boolean
  supports_verbosity: boolean
  supports_session_cache: boolean
  heartbeat_supported: boolean
  warnings: string[]
}

export interface HeartbeatTriggerResponse {
  status: string
  message: string
  session_id: string | null
}

export async function fetchHeartbeatStatus(): Promise<HeartbeatStatusResponse> {
  const response = await fetchApi(`${API_BASE}/heartbeat/status`)
  if (!response.ok) {
    throw new Error(`Heartbeat status fetch failed: ${response.status}`)
  }
  return response.json()
}

export async function triggerHeartbeat(): Promise<HeartbeatTriggerResponse> {
  const response = await fetchApi(`${API_BASE}/heartbeat/trigger`, {
    method: 'POST',
  })
  if (response.status === 409) {
    const data = await response.json().catch(() => ({}))
    throw new HeartbeatConflictError(
      typeof data.message === 'string'
        ? data.message
        : 'Heartbeat already in progress',
      typeof data.running_session_id === 'string'
        ? data.running_session_id
        : null,
    )
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(
      data.message || `Heartbeat trigger failed: ${response.status}`,
    )
  }
  return response.json()
}

export class HeartbeatConflictError extends Error {
  runningSessionId: string | null

  constructor(message: string, runningSessionId: string | null = null) {
    super(message)
    this.name = 'HeartbeatConflictError'
    this.runningSessionId = runningSessionId
  }
}
