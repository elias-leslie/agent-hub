// API functions for admin page

import { fetchApi } from '@/lib/api-config'

export interface HotspotTotals {
  sessions: number
  input_tokens: number
  output_tokens: number
  total_cost_usd: number
  active_sessions: number
  zero_event_active_sessions: number
  rate_limit_fallback_sessions: number
  missing_attribution_sessions: number
}

export interface HotspotBreakdownRow {
  kind: string
  label: string
  sessions: number
  input_tokens: number
  output_tokens: number
  total_cost_usd: number
}

export interface RepeatedWorkloadRow {
  workload_key: string
  label: string
  detail: string | null
  project_id: string
  agent_slug: string | null
  sessions: number
  input_tokens: number
  output_tokens: number
  total_cost_usd: number
}

export interface LowYieldSessionRow {
  session_id: string
  project_id: string
  agent_slug: string | null
  status: string
  model: string
  label: string
  input_tokens: number
  output_tokens: number
  total_cost_usd: number
  attribution_label: string | null
  efficiency_ratio: number
}

export interface ZeroEventActiveSessionRow {
  session_id: string
  project_id: string
  agent_slug: string | null
  request_source: string | null
  quiet_for_seconds: number
  lifecycle_state: string | null
}

export interface SessionHotspots {
  generated_at: string
  window_hours: number
  totals: HotspotTotals
  attribution_breakdown: HotspotBreakdownRow[]
  repeated_workloads: RepeatedWorkloadRow[]
  low_yield_sessions: LowYieldSessionRow[]
  zero_event_active_sessions: ZeroEventActiveSessionRow[]
}

export interface RequestBlockStats {
  blocked_requests_today: number
  unknown_client_requests_today: number
  total_requests_today: number
}

// Counts come from request_logs since 00:00 UTC (see /api/access-control/stats).
export async function fetchRequestBlockStats(): Promise<RequestBlockStats> {
  const res = await fetchApi('/api/access-control/stats')
  if (!res.ok) throw new Error('Failed to fetch request block stats')
  return res.json()
}

export async function fetchSessionHotspots(
  hours = 24,
  limit = 5,
): Promise<SessionHotspots> {
  const params = new URLSearchParams({
    hours: String(hours),
    limit: String(limit),
  })
  const res = await fetchApi(`/api/admin/session-hotspots?${params.toString()}`)
  if (!res.ok) throw new Error('Failed to fetch session hotspots')
  return res.json()
}
