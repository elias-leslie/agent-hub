export interface Agent {
  id: number;
  slug: string;
  name: string;
  primary_model_id: string;
  fallback_models: string[];
  updated_at: string;
}

export interface AgentMetrics {
  slug: string;
  requests_24h: number;
  avg_latency_ms: number;
  success_rate: number;
  tokens_24h: number;
  cost_24h_usd: number;
  latency_trend: number[];
  success_trend: number[];
}

export type AnalyticsWindow = 6 | 12 | 24;

export interface TrendPoint {
  hour: string;
  latencyMs: number;
  successRate: number;
}

export interface AnalyticsData {
  totalCostUsd: number;
  avgLatencyMs: number;
  errorRate: number;
  successRate: number;
  totalRequests: number;
  totalTokens: number;
  requestsPerHour: number;
  trend: TrendPoint[];
  modelSummary: string[];
  lastUpdatedAt: string;
}

export interface AgentBenchmarkOverview {
  total_runs: number;
  avg_score: number;
  pass_rate: number;
  open_regressions: number;
  latest_completed_at: string | null;
  tracked_models: string[];
}

export interface AgentBenchmarkTrendPoint {
  run_id: string;
  completed_at: string | null;
  suite_id: string;
  run_kind: string;
  avg_score: number | null;
  pass_rate: number | null;
  attempts: number;
  prompt_version: string | null;
}

export interface AgentBenchmarkRunSummary {
  run_id: string;
  benchmark_id: string;
  suite_id: string;
  run_kind: string;
  started_at: string;
  completed_at: string | null;
  avg_score: number | null;
  pass_rate: number | null;
  attempt_count: number;
  passed_attempt_count: number;
  infra_failure_count: number;
  models: string[];
  case_ids: string[];
  config_snapshot: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export interface AgentRegressionClusterSummary {
  regression_key: string;
  suite_id: string;
  case_id: string;
  failure_detail: string;
  status: string;
  occurrence_count: number;
  latest_avg_score: number | null;
  affected_models: string[];
  opened_at: string | null;
  last_seen_at: string | null;
  resolved_at: string | null;
}

export interface AgentBenchmarkModelSummary {
  model_id: string;
  attempts: number;
  avg_score: number | null;
  pass_rate: number;
  avg_latency_ms: number | null;
  latest_completed_at: string | null;
}

export interface AgentBenchmarkDashboard {
  agent_slug: string;
  overview: AgentBenchmarkOverview;
  trend: AgentBenchmarkTrendPoint[];
  recent_runs: AgentBenchmarkRunSummary[];
  open_regressions: AgentRegressionClusterSummary[];
  model_performance: AgentBenchmarkModelSummary[];
}
