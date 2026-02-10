export interface Agent {
  id: number;
  slug: string;
  name: string;
  primary_model_id: string;
  fallback_models: string[];
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

export interface AnalyticsData {
  total_cost_usd: number;
  avg_latency_ms: number;
  error_rate: number;
  cache_hit_rate: number;
  total_requests: number;
  model_distribution: { model: string; count: number; percentage: number }[];
  latency_histogram: { range: string; count: number }[];
  recent_failures: {
    id: string;
    timestamp: string;
    error_type: string;
    message: string;
    model: string;
  }[];
  trend: {
    cost_change: number;
    latency_change: number;
    error_change: number;
  };
}
