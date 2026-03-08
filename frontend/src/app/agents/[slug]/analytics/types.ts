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
