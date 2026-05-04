// API functions for admin page

import { fetchApi } from '@/lib/api-config'

export interface ClientControl {
  client_name: string
  enabled: boolean
  disabled_at: string | null
  disabled_by: string | null
  reason: string | null
  created_at: string
  updated_at: string
}

export interface BlockedRequest {
  timestamp: string
  client_name: string | null
  source_path: string | null
  block_reason: string
  endpoint: string
}

export interface WorkflowSchedule {
  schedule_id: string
  label: string
  description: string
  cron: string
  category: string
  default_enabled: boolean
  enabled: boolean
  notes: string | null
  updated_by: string | null
}

export interface WorkflowScheduleUpdate {
  enabled: boolean
  updated_by?: string | null
}

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

export async function fetchClients(): Promise<ClientControl[]> {
  const res = await fetchApi('/api/admin/clients')
  const data = await res.json()
  return data.clients || []
}

export async function fetchBlockedRequests(): Promise<BlockedRequest[]> {
  const res = await fetchApi('/api/admin/blocked-requests?limit=1000')
  const data = await res.json()
  return data.requests || []
}

export async function fetchWorkflowSchedules(): Promise<WorkflowSchedule[]> {
  const res = await fetchApi('/api/admin/schedules')
  if (!res.ok) throw new Error('Failed to fetch workflow schedules')
  return res.json()
}

export async function updateWorkflowSchedule(
  scheduleId: string,
  payload: WorkflowScheduleUpdate,
): Promise<WorkflowSchedule> {
  const res = await fetchApi(`/api/admin/schedules/${scheduleId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(`Failed to update schedule ${scheduleId}`)
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

export async function disableClient(
  clientName: string,
  reason: string,
  disabledBy: string,
): Promise<void> {
  await fetchApi(`/api/admin/clients/${clientName}/disable`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason, disabled_by: disabledBy }),
  })
}

export async function enableClient(clientName: string): Promise<void> {
  await fetchApi(`/api/admin/clients/${clientName}/disable`, {
    method: 'DELETE',
  })
}
