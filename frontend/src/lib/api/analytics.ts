/**
 * Analytics API for costs and truncations
 */

import { fetchApi, getApiBaseUrl } from '../api-config'

const API_BASE = `${getApiBaseUrl()}/api`

export interface CostAggregation {
  group_key: string
  total_tokens: number
  input_tokens: number
  output_tokens: number
  /** Marginal cash cost; Claude/Codex subscription calls are $0. */
  total_cost_usd: number
  request_count: number
  /** API-equivalent value at list price. Value received, not spend. */
  api_equiv_usd?: number
  credits_used?: number
}

export interface CostAggregationResponse {
  aggregations: CostAggregation[]
  total_cost_usd: number
  total_tokens: number
  total_requests: number
  total_api_equiv_usd?: number
  total_credits_used?: number
}

export async function fetchCosts(params: {
  group_by?: 'project' | 'model' | 'day' | 'week' | 'month' | 'none'
  days?: number
  project_id?: string
  model?: string
}): Promise<CostAggregationResponse> {
  const searchParams = new URLSearchParams()
  if (params.group_by) searchParams.set('group_by', params.group_by)
  if (params.days) searchParams.set('days', params.days.toString())
  if (params.project_id) searchParams.set('project_id', params.project_id)
  if (params.model) searchParams.set('model', params.model)

  const response = await fetchApi(`${API_BASE}/analytics/costs?${searchParams}`)
  if (!response.ok) {
    throw new Error(`Costs fetch failed: ${response.status}`)
  }
  return response.json()
}

export interface UsageWindow {
  window_minutes: number
  label: string
  used_percent: number
  resets_at: string | null
  observed_at: string
  reset_since_observed: boolean
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

export interface SpendPatternsResponse {
  window_days: number
  generated_at: string
  unavailable: string[]
  unpriced: {
    calls: number
    unpriced_calls: number
    models: Array<{ model: string; calls: number; tokens: number }>
  } | null
  effort: {
    levels: Array<{ effort: string; sessions: number; tokens: number }>
    sessions_with_effort: number
    high_session_share: number | null
    high_token_share: number | null
  } | null
  model_names: {
    sessions: number
    names: Array<{ model: string; kind: string; sessions: number }>
  } | null
  empty_sessions: {
    sessions: number
    by_source: Array<{ project: string; source: string; sessions: number }>
  } | null
  repeated_calls: {
    window_minutes: number
    repeats: number
    by_caller: Array<{ project: string; source: string; repeats: number }>
  } | null
  gated_automations: {
    enabled: number
    gated: Array<{ label: string; project: string; reasons: string[] }>
  } | null
  weekly_spike: {
    measure: 'cash' | 'tokens'
    current: number
    usual: number
    ratio: number | null
    spike: boolean
  } | null
}

/** Where model spend is wasted or can't be priced, over the last `days`. */
export async function fetchSpendPatterns(
  days: number,
): Promise<SpendPatternsResponse> {
  const response = await fetchApi(
    `${API_BASE}/analytics/spend-patterns?days=${days}`,
  )
  if (!response.ok) {
    throw new Error(`Spend patterns fetch failed: ${response.status}`)
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
