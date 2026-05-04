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
  total_cost_usd: number
  request_count: number
}

export interface CostAggregationResponse {
  aggregations: CostAggregation[]
  total_cost_usd: number
  total_tokens: number
  total_requests: number
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
