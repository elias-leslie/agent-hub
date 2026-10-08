// ─────────────────────────────────────────────────────────────────────────────
// TYPES
// ─────────────────────────────────────────────────────────────────────────────

export interface Agent {
  id: number
  slug: string
  name: string
  description: string | null
  primary_model_id: string
  fallback_models: string[]
  temperature: number
  is_active: boolean
  is_coding_agent: boolean
  version: number
  created_at: string
  updated_at: string
}

export interface AgentListResponse {
  agents: Agent[]
  total: number
}

export interface AgentMetrics {
  slug: string
  requests_24h: number
  avg_latency_ms: number
  success_rate: number
  tokens_24h: number
  cost_24h_usd: number
  latency_trend: number[]
  success_trend: number[]
}

export interface AgentMetricsResponse {
  metrics: Record<string, AgentMetrics>
}

// Sort types
export type SortField = 'name' | 'model' | 'requests' | 'latency' | 'cost'
export type SortDirection = 'asc' | 'desc'

// Benchmark run detail (consumed by the agents API client and the persona
// improvement dashboard)
export interface AgentBenchmarkAttemptDetail {
  id: string
  model_id: string
  case_id: string
  case_name: string | null
  run_number: number
  passed: boolean
  composite_score: number
  correctness_score: number
  primary_action: string | null
  confidence: string | null
  summary: string | null
  failure_kind: string | null
  failure_detail: string | null
  infra_failure: boolean
  tool_requirement_met: boolean
  latency_ms: number
  total_tokens: number
  turns: number
  tool_calls_count: number
  fallback_used: boolean
  provider: string | null
  effective_model: string | null
}

export interface AgentBenchmarkRunDetail {
  run_id: string
  benchmark_id: string
  suite_id: string
  run_kind: string
  started_at: string
  completed_at: string | null
  avg_score: number | null
  pass_rate: number | null
  attempt_count: number
  passed_attempt_count: number
  infra_failure_count: number
  models: string[]
  case_ids: string[]
  attempts: AgentBenchmarkAttemptDetail[]
}
