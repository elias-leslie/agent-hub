export interface Agent {
  id: number
  slug: string
  name: string
  primary_model_id: string
  fallback_models: string[]
  updated_at: string
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

export type AnalyticsWindow = 6 | 12 | 24

export interface TrendPoint {
  hour: string
  latencyMs: number
  successRate: number
}

export interface AnalyticsData {
  totalCostUsd: number
  avgLatencyMs: number
  errorRate: number
  successRate: number
  totalRequests: number
  totalTokens: number
  requestsPerHour: number
  trend: TrendPoint[]
  modelSummary: string[]
  lastUpdatedAt: string
}

export interface AgentBenchmarkOverview {
  total_runs: number
  avg_score: number
  pass_rate: number
  open_regressions: number
  latest_completed_at: string | null
  tracked_models: string[]
}

export interface AgentBenchmarkTrendPoint {
  run_id: string
  completed_at: string | null
  suite_id: string
  run_kind: string
  avg_score: number | null
  pass_rate: number | null
  attempts: number
  prompt_version: string | null
}

export interface AgentBenchmarkRunSummary {
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
  config_snapshot: Record<string, unknown>
  metadata: Record<string, unknown>
}

export interface AgentRegressionClusterSummary {
  regression_key: string
  suite_id: string
  case_id: string
  failure_detail: string
  status: string
  occurrence_count: number
  latest_avg_score: number | null
  affected_models: string[]
  opened_at: string | null
  last_seen_at: string | null
  resolved_at: string | null
}

export interface AgentBenchmarkModelSummary {
  model_id: string
  attempts: number
  avg_score: number | null
  pass_rate: number
  avg_latency_ms: number | null
  avg_total_tokens: number | null
  avg_turns: number | null
  avg_tool_calls: number | null
  latest_completed_at: string | null
}

export interface AgentBenchmarkSuiteSummary {
  suite_id: string
  run_count: number
  avg_score: number | null
  pass_rate: number
  open_regressions: number
  latest_completed_at: string | null
  tracked_models: string[]
  case_ids: string[]
  run_kinds: string[]
}

export interface AgentBenchmarkCaseSummary {
  case_id: string
  case_name: string | null
  attempts: number
  pass_rate: number
  avg_score: number | null
  open_regressions: number
  latest_completed_at: string | null
  latest_failure_detail: string | null
  tracked_models: string[]
  suite_ids: string[]
}

export interface AgentBenchmarkExperimentArmSummary {
  label: string
  run_count: number
  avg_score: number | null
  avg_pass_rate: number | null
  avg_total_tokens: number | null
  avg_turns: number | null
  avg_tool_calls: number | null
  config_fingerprints: string[]
  config_stable: boolean
  prompt_versions: string[]
  latest_completed_at: string | null
}

export interface AgentBenchmarkDeltaSummary {
  mean_delta: number | null
  ci_low: number | null
  ci_high: number | null
}

export interface AgentBenchmarkExperimentSummary {
  experiment_key: string
  name: string
  suite_id: string
  status: string
  decision: string
  decision_reason: string | null
  hypothesis: string | null
  min_runs_per_cohort: number
  baseline: AgentBenchmarkExperimentArmSummary
  candidate: AgentBenchmarkExperimentArmSummary
  score_delta: AgentBenchmarkDeltaSummary
  pass_rate_delta: AgentBenchmarkDeltaSummary
  tool_call_delta: AgentBenchmarkDeltaSummary
  updated_at: string | null
  created_at: string | null
}

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

export interface AgentBenchmarkDashboard {
  agent_slug: string
  overview: AgentBenchmarkOverview
  trend: AgentBenchmarkTrendPoint[]
  recent_runs: AgentBenchmarkRunSummary[]
  open_regressions: AgentRegressionClusterSummary[]
  model_performance: AgentBenchmarkModelSummary[]
  suites: AgentBenchmarkSuiteSummary[]
  cases: AgentBenchmarkCaseSummary[]
  experiments: AgentBenchmarkExperimentSummary[]
}
