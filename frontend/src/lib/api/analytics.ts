/**
 * Analytics API for costs and truncations
 */

import { fetchApi, getApiBaseUrl } from '../api-config'

const API_BASE = `${getApiBaseUrl()}/api`

export interface UsageWindow {
  window_minutes: number
  label: string
  used_percent: number
  resets_at: string | null
  observed_at: string
  reset_since_observed: boolean
  /** Where the reading came from (null for readings stored before sources were recorded). */
  source?: string | null
  source_label?: string | null
}

export interface ProviderUtilization {
  provider: string
  plan_type: string | null
  windows: UsageWindow[]
}

export interface CreditLotState {
  id: number
  source: 'grant' | 'purchase' | 'unclassified'
  credits: number
  remaining: number
  remaining_fraction: number | null
  granted_at: string
  expires_at: string | null
  days_to_expiry: number | null
  value_usd_per_credit: number | null
  paid_usd: number | null
  remaining_value_usd: number | null
  projected_unused_at_expiry: number | null
  evidence: string | null
}

export interface CostAlert {
  code: string
  severity: 'info' | 'warning' | 'critical'
  message: string
  resets_at?: string | null
}

export interface CostAccountingResponse {
  as_of: string
  window: { start: string; end: string; days: number }
  cash: {
    total_usd: number
    subscriptions_usd: number
    metered_api_usd: number
    credit_purchases_usd: number
    month_to_date_usd: number
    projected_month_usd: number
    subscriptions: Array<{
      provider: string
      plan: string
      monthly_usd: number | null
      amortized_usd: number
      days: number
    }>
    unverified_plans: Array<{ provider: string; plan: string }>
    daily: Array<{
      date: string
      subscriptions_usd: number
      metered_usd: number
      credit_purchases_usd: number
    }>
  }
  utilization: ProviderUtilization[]
  credits: {
    provider: string
    used_in_window: number
    balance: number
    burn_per_day_7d: number
    cash_usd_in_window: number
    daily: Array<{ date: string; credits: number }>
    by_project: Array<{ project: string; credits: number }>
    lots: CreditLotState[]
    attribution_note: string
  }
  api_equivalent: {
    label: string
    total_usd: number
    by_provider: Array<{
      provider: string
      api_equiv_usd: number
      tokens: number
      unpriced_tokens: number
      fee_usd: number
      leverage: number | null
    }>
    by_model: Array<{ provider: string; model: string; api_equiv_usd: number }>
    by_project: Array<{
      project: string
      api_equiv_usd: number
      share: number | null
      allocated_fee_usd: number
    }>
    by_agent: Array<{
      agent: string
      api_equiv_usd: number
      credits: number
      requests: number
    }>
  }
  alerts: CostAlert[]
}

/** Cash, subscription headroom, Codex credits and API-equivalent value, kept separate. */
export async function fetchCostAccounting(
  days: number,
): Promise<CostAccountingResponse> {
  const response = await fetchApi(
    `${API_BASE}/analytics/costs/accounting?days=${days}`,
  )
  if (!response.ok) {
    throw new Error(`Cost accounting fetch failed: ${response.status}`)
  }
  return response.json()
}

export type SpendRange = '1h' | '24h' | '7d' | '30d'
export type SpendKind = 'interactive' | 'routine' | 'other'

export interface SpendSummary {
  rate_per_hour: number
  rate_typical: number | null
  rate_ratio: number | null
  today: number
  today_typical: number | null
  today_ratio: number | null
  week: number
  week_typical: number | null
  week_ratio: number | null
  data_since: string | null
}

export interface SpendBar {
  start: string
  interactive: number
  routine: number
  other: number
}

export interface SpendItem {
  key: string
  name: string
  kind: SpendKind
  project: string
  usd: number
  share: number
  tokens: number
  calls: number
  spark: number[]
}

export interface SpendCoverage {
  percent: number | null
  sessions: number
  captured: number
  uncaptured: Array<{ source: string; sessions: number }>
}

export interface SpendOverview {
  range: SpendRange
  start: string
  end: string
  bucket_seconds: number
  selected_bucket: string | null
  summary: SpendSummary
  chart: SpendBar[]
  total_usd: number
  unpriced_calls: number
  item_count: number
  items: SpendItem[]
  filters: { project: string[]; model: string[]; kind: SpendKind[] }
  coverage: SpendCoverage
}

export interface SpendFilters {
  project?: string | null
  model?: string | null
  kind?: SpendKind | null
}

/** Agent spend (Claude Code, Codex and completions at API list price) for the Costs page. */
export async function fetchSpend(
  range: SpendRange,
  filters: SpendFilters = {},
  bucket?: string | null,
): Promise<SpendOverview> {
  const params = new URLSearchParams({ range })
  if (bucket) params.set('bucket', bucket)
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value)
  }
  const response = await fetchApi(`${API_BASE}/analytics/spend?${params}`)
  if (!response.ok) {
    throw new Error(`Spend fetch failed: ${response.status}`)
  }
  return response.json()
}

export interface SpendItemDetail {
  key: string
  name: string
  kind: SpendKind | null
  project: string | null
  range: SpendRange
  bucket_seconds: number
  total_usd: number
  tokens: number
  calls: number
  timeline: Array<{ start: string; usd: number }>
  agents: Array<{
    key: string
    name: string
    usd: number
    tokens: number
    calls: number
  }>
  models: Array<{ model: string; usd: number; tokens: number; calls: number }>
  top_calls: Array<{
    at: string
    model: string
    agent: string
    tokens: number
    usd: number
  }>
  runs: {
    count: number
    cost_per_run: number
    median_run: number
    per_day: number
  } | null
}

export async function fetchSpendItem(
  key: string,
  range: SpendRange,
): Promise<SpendItemDetail> {
  const params = new URLSearchParams({ key, range })
  const response = await fetchApi(`${API_BASE}/analytics/spend/item?${params}`)
  if (!response.ok) {
    throw new Error(`Spend item fetch failed: ${response.status}`)
  }
  return response.json()
}

export interface TruncationAggregation {
  group_key: string
  truncation_count: number
  avg_output_tokens: number
  avg_max_tokens: number
  capped_count: number
}

export interface TruncationMetricsResponse {
  aggregations: TruncationAggregation[]
  total_truncations: number
  truncation_rate: number
  recent_events: Array<{
    id: number
    model: string
    endpoint: string
    output_tokens: number
    max_tokens_requested: number
    model_limit: number
    was_capped: boolean
    created_at: string | null
  }>
}

export async function fetchTruncations(params?: {
  group_by?: 'model' | 'day' | 'week' | 'month' | 'none'
  model?: string
  project_id?: string
  days?: number
  include_recent?: boolean
  limit_recent?: number
}): Promise<TruncationMetricsResponse> {
  const searchParams = new URLSearchParams()
  if (params?.group_by) searchParams.set('group_by', params.group_by)
  if (params?.model) searchParams.set('model', params.model)
  if (params?.project_id) searchParams.set('project_id', params.project_id)
  if (params?.days) searchParams.set('days', params.days.toString())
  if (params?.include_recent !== undefined)
    searchParams.set('include_recent', params.include_recent.toString())
  if (params?.limit_recent)
    searchParams.set('limit_recent', params.limit_recent.toString())

  const url = searchParams.toString()
    ? `${API_BASE}/analytics/truncations?${searchParams}`
    : `${API_BASE}/analytics/truncations`

  const response = await fetchApi(url)
  if (!response.ok) {
    throw new Error(`Truncations fetch failed: ${response.status}`)
  }
  return response.json()
}

export interface OpenCodeGoWindow {
  key: 'rolling' | 'weekly' | 'monthly'
  label: string
  status: string
  percent: number
  resets_at: string | null
}

/** OpenCode Go quota as OpenCode reports it; `reason` explains anything but `ok`. */
export interface OpenCodeGoUsage {
  provider: 'opencode-go'
  state: 'ok' | 'unavailable' | 'not_configured'
  reason: string | null
  windows: OpenCodeGoWindow[]
  fetched_at: string
}

export async function fetchOpenCodeGoUsage(): Promise<OpenCodeGoUsage> {
  const response = await fetchApi(
    `${API_BASE}/analytics/subscriptions/opencode-go/usage`,
  )
  if (!response.ok) {
    throw new Error(`OpenCode Go usage fetch failed: ${response.status}`)
  }
  return response.json()
}
